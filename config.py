"""Application settings loaded from a .env file or Streamlit secrets."""
import os
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


def _load_streamlit_secrets() -> None:
    """Inject Streamlit Cloud secrets into os.environ before settings are loaded."""
    try:
        import streamlit as st
        for key, value in st.secrets.items():
            if isinstance(value, str):
                os.environ[key.upper()] = value
            elif hasattr(value, "items"):
                for k, v in value.items():
                    if isinstance(v, str):
                        os.environ[k.upper()] = v
    except Exception:
        pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = "sqlite:///./learn_ai.db"

    # Groq (required for content generation)
    groq_api_key: Optional[str] = None
    groq_model: str = "llama3-70b-8192"

    # Notion (optional)
    notion_api_key: Optional[str] = None
    notion_root_page_id: Optional[str] = None

    # Application
    app_env: str = "development"
    log_level: str = "INFO"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


_load_streamlit_secrets()
settings = Settings()