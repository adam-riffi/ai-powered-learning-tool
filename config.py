"""Application configuration loaded from .env file."""
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = "sqlite:///./learn_ai.db"

    # Notion (optional — only needed for notion_tool)
    notion_api_key: Optional[str] = None
    notion_root_page_id: Optional[str] = None

    # Application
    app_env: str = "development"
    log_level: str = "INFO"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


settings = Settings()
