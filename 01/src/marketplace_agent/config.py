"""Validated environment settings without connecting to external services."""

from typing import Literal

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Load environment variables, then .env in the current working directory."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    marketplace_mode: Literal["demo", "live"] = "demo"
    app_host: str = Field(default="0.0.0.0", min_length=1)
    app_port: int = Field(default=8080, ge=1, le=65535)

    llm_base_url: AnyHttpUrl | None = None
    llm_model: str | None = Field(default=None, min_length=1)
    agentgateway_url: AnyHttpUrl | None = None
    bazos_mcp_url: AnyHttpUrl | None = None
    sbazar_mcp_url: AnyHttpUrl | None = None
