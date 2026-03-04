"""OAuth authentication helpers.

Manages the OAuth flow using query parameters for the callback,
compatible with Google and GitHub providers.

This module is designed to be replaced by Supabase Auth at a later stage:
- `exchange_code_for_user()` will be swapped for `supabase.auth.exchange_code_for_session()`
- `build_oauth_url()` will be swapped for `supabase.auth.sign_in_with_oauth()`
- `UserSession` structure stays identical so no page code changes

Requires in .env:
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
    GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET
    APP_BASE_URL (default: http://localhost:8501)
"""
import os
import urllib.parse
from dataclasses import dataclass
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

APP_BASE_URL: str = os.environ.get("APP_BASE_URL", "http://localhost:8501")

_PROVIDERS: dict[str, dict] = {
    "google": {
        "client_id":     os.environ.get("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url":     "https://oauth2.googleapis.com/token",
        "userinfo_url":  "https://www.googleapis.com/oauth2/v3/userinfo",
        "scope":         "openid email profile",
    },
    "github": {
        "client_id":     os.environ.get("GITHUB_CLIENT_ID", ""),
        "client_secret": os.environ.get("GITHUB_CLIENT_SECRET", ""),
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url":     "https://github.com/login/oauth/access_token",
        "userinfo_url":  "https://api.github.com/user",
        "scope":         "read:user user:email",
    },
}


@dataclass
class UserSession:
    """Normalised user object, identical for Google and GitHub."""
    id: str
    email: str
    name: str
    avatar: Optional[str]
    provider: str


# ---------------------------------------------------------------------------
# URL builder
# ---------------------------------------------------------------------------

def build_oauth_url(provider: str) -> str:
    """
    Return the authorization URL to redirect the user to.

    The redirect_uri points back to Streamlit so query params carry
    the authorization code after the provider redirects.
    """
    if provider not in _PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")

    cfg = _PROVIDERS[provider]
    redirect_uri = f"{APP_BASE_URL}/?provider={provider}"

    params = {
        "client_id":     cfg["client_id"],
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         cfg["scope"],
    }

    if provider == "google":
        params["access_type"] = "online"

    return cfg["authorize_url"] + "?" + urllib.parse.urlencode(params)


# ---------------------------------------------------------------------------
# Code exchange
# ---------------------------------------------------------------------------

def exchange_code_for_user(provider: str, code: str) -> UserSession:
    """
    Exchange the authorization code for an access token, then fetch user info.
    Returns a normalised UserSession.
    """
    if provider not in _PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")

    cfg = _PROVIDERS[provider]
    redirect_uri = f"{APP_BASE_URL}/?provider={provider}"

    token_response = requests.post(
        cfg["token_url"],
        data={
            "client_id":     cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "code":          code,
            "redirect_uri":  redirect_uri,
            "grant_type":    "authorization_code",
        },
        headers={"Accept": "application/json"},
        timeout=10,
    )
    token_response.raise_for_status()
    token_data = token_response.json()
    access_token = token_data.get("access_token")

    if not access_token:
        raise RuntimeError(f"No access token in response: {token_data}")

    return _fetch_user(provider, cfg, access_token)


def _fetch_user(provider: str, cfg: dict, access_token: str) -> UserSession:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    resp = requests.get(cfg["userinfo_url"], headers=headers, timeout=10)
    resp.raise_for_status()
    info = resp.json()

    if provider == "google":
        return UserSession(
            id=info["sub"],
            email=info["email"],
            name=info.get("name", info["email"]),
            avatar=info.get("picture"),
            provider="google",
        )

    # GitHub — email may require a second call
    email = info.get("email")
    if not email:
        email = _fetch_github_primary_email(access_token)

    return UserSession(
        id=str(info["id"]),
        email=email or "",
        name=info.get("name") or info.get("login", ""),
        avatar=info.get("avatar_url"),
        provider="github",
    )


def _fetch_github_primary_email(access_token: str) -> Optional[str]:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    resp = requests.get("https://api.github.com/user/emails", headers=headers, timeout=10)
    if not resp.ok:
        return None
    emails = resp.json()
    primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
    return primary["email"] if primary else None