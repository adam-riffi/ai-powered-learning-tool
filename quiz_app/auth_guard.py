"""Page access control and user sidebar rendering.

Usage — add at the top of every protected page, after imports:

    from auth_guard import require_auth, render_sidebar_user

    require_auth()
    render_sidebar_user()

`current_user_id()` is the single point used by tools to scope data
to the logged-in user. When Supabase is wired in, nothing changes here.
"""
import streamlit as st

from auth import UserSession, build_oauth_url


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def load_user_from_callback() -> None:
    """
    Detect an OAuth callback via query params, exchange the code,
    and store the user in session_state.

    Must be called once per page load (before require_auth).
    Clears the query params from the URL after processing.
    """
    params = st.query_params

    code: str = params.get("code", "")
    provider: str = params.get("provider", "")

    if not code or not provider:
        return

    if st.session_state.get("user"):
        st.query_params.clear()
        return

    try:
        from auth import exchange_code_for_user
        user: UserSession = exchange_code_for_user(provider, code)
        st.session_state["user"] = user
        st.session_state["user_id"] = user.id
    except Exception as exc:
        st.session_state["oauth_error"] = str(exc)
    finally:
        st.query_params.clear()


def current_user() -> UserSession | None:
    return st.session_state.get("user")


def current_user_id() -> str | None:
    """Return the logged-in user's ID, or None. Used by tools to filter data."""
    return st.session_state.get("user_id")


# ---------------------------------------------------------------------------
# Page guard
# ---------------------------------------------------------------------------

def require_auth() -> None:
    """
    Redirect to the login page if no user is in session.
    If an OAuth callback is in progress, process it first before redirecting.
    Call this at the top of every protected page.
    """
    load_user_from_callback()

    if st.session_state.get("oauth_error"):
        st.error(f"Authentication error: {st.session_state.pop('oauth_error')}")

    if not st.session_state.get("user"):
        if st.query_params.get("code"):
            st.spinner("Connexion en cours...")
            st.rerun()
        st.switch_page("pages/5_Login.py")


# ---------------------------------------------------------------------------
# UI components
# ---------------------------------------------------------------------------

def render_sidebar_user() -> None:
    """Display the logged-in user and a logout button in the sidebar."""
    user: UserSession | None = st.session_state.get("user")
    if not user:
        return

    with st.sidebar:
        st.divider()
        cols = st.columns([1, 3])
        with cols[0]:
            if user.avatar:
                st.image(user.avatar, width=36)
        with cols[1]:
            st.markdown(f"**{user.name}**")
            st.caption(user.email)
        if st.button("Logout", use_container_width=True, key="_sidebar_logout"):
            st.session_state.clear()
            st.rerun()


def _render_login_buttons() -> None:
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.link_button(
            "Sign in with Google",
            build_oauth_url("google"),
            use_container_width=True,
        )
    with col2:
        st.link_button(
            "Sign in with GitHub",
            build_oauth_url("github"),
            use_container_width=True,
        )