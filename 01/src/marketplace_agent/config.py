"""Validated environment settings without connecting to external services."""

from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr
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

    unsloth_base_url: AnyHttpUrl = AnyHttpUrl("http://host.docker.internal:8888/v1")
    unsloth_model: str | None = Field(default=None, min_length=1)
    unsloth_api_key: SecretStr = SecretStr("")
    llm_timeout: float = Field(default=120, gt=0, le=3600)
    agent_max_iterations: int = Field(default=8, ge=1, le=50)
    agent_max_tool_calls: int = Field(default=8, ge=1, le=32)
    agent_history_turns: int = Field(default=6, ge=1, le=50)
    agent_history_chars: int = Field(default=64000, ge=2000, le=1000000)
    agent_max_message_chars: int = Field(default=4000, ge=1, le=32000)
    agent_max_tokens: int = Field(default=4096, ge=256, le=32768)
    mcp_timeout: float = Field(default=30, gt=0, le=300)
