"""Application configuration loaded from environment variables."""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed settings exposed across the app."""

    gemini_api_token: str = Field(..., alias="GEMINI_API_TOKEN")
    gemini_model: str = Field("gemini-2.5-flash", alias="GEMINI_MODEL")

    app_host: str = Field("0.0.0.0", alias="APP_HOST")
    app_port: int = Field(8080, alias="APP_PORT")

    cors_origins: List[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        alias="CORS_ORIGINS",
    )
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    crawl_page_timeout_ms: int = Field(60_000, alias="CRAWL_PAGE_TIMEOUT_MS")
    crawl_headless: bool = Field(True, alias="CRAWL_HEADLESS")

    llm_max_retries: int = Field(3, alias="LLM_MAX_RETRIES")
    llm_request_timeout_s: int = Field(60, alias="LLM_REQUEST_TIMEOUT_S")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
