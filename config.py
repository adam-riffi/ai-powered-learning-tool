"""Application settings.

On Streamlit Cloud, DATABASE_URL and other secrets are injected into
os.environ automatically AFTER module import. Settings must therefore
be read lazily (at call time), not at module import time.

For local development, values are loaded from a .env file via python-dotenv.
"""
import os

from dotenv import load_dotenv

load_dotenv()


def get_database_url() -> str:
    """Return DATABASE_URL, reading from os.environ at call time."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    raise RuntimeError(
        "DATABASE_URL is not set. "
        "Add it as a root-level key in your Streamlit secrets (Streamlit Cloud) "
        "or in your .env file (local development)."
    )


def get_groq_api_key() -> str | None:
    return os.environ.get("GROQ_API_KEY") or os.environ.get("groq_api_key")


def get_groq_model() -> str:
    return os.environ.get("GROQ_MODEL") or os.environ.get("groq_model") or "llama3-70b-8192"


def get_notion_api_key() -> str | None:
    return os.environ.get("NOTION_API_KEY")


def get_notion_root_page_id() -> str | None:
    return os.environ.get("NOTION_ROOT_PAGE_ID")


def get_app_env() -> str:
    return os.environ.get("APP_ENV", "production")


class _Settings:
    """
    Lazy settings object. Each property reads from os.environ at access time,
    so Streamlit Cloud secrets (injected after import) are always visible.
    """

    @property
    def database_url(self) -> str:
        return get_database_url()

    @property
    def groq_api_key(self) -> str | None:
        return get_groq_api_key()

    @groq_api_key.setter
    def groq_api_key(self, value: str) -> None:
        os.environ["GROQ_API_KEY"] = value

    @property
    def groq_model(self) -> str:
        return get_groq_model()

    @groq_model.setter
    def groq_model(self, value: str) -> None:
        os.environ["GROQ_MODEL"] = value

    @property
    def notion_api_key(self) -> str | None:
        return get_notion_api_key()

    @property
    def notion_root_page_id(self) -> str | None:
        return get_notion_root_page_id()

    @property
    def app_env(self) -> str:
        return get_app_env()

    @property
    def is_sqlite(self) -> bool:
        try:
            return self.database_url.startswith("sqlite")
        except RuntimeError:
            return False


settings = _Settings()