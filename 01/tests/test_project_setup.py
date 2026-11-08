"""Configuration and packaging checks for the web-only application."""

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from marketplace_agent.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    for key in tuple(os.environ):
        if key.lower() in Settings.model_fields:
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)


def test_defaults_do_not_require_future_services() -> None:
    settings = Settings()
    assert settings.app_env == "development"
    assert settings.marketplace_mode == "demo"
    assert settings.app_port == 8080
    assert settings.llm_base_url is None
    assert settings.llm_model is None
    assert settings.agentgateway_url is None
    assert settings.bazos_mcp_url is None
    assert settings.sbazar_mcp_url is None


def test_environment_overrides_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "APP_ENV=production\nAPP_PORT=9090\nLOG_LEVEL=DEBUG\nUNRELATED_COMPOSE_KEY=value\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_ENV", "test")
    settings = Settings()
    assert settings.app_env == "test"
    assert settings.app_port == 9090
    assert settings.log_level == "DEBUG"


def test_example_configuration_is_valid() -> None:
    settings = Settings(_env_file=PROJECT_ROOT / ".env.example")
    assert settings.unsloth_model == "your-loaded-model-id"
    assert settings.llm_base_url is not None
    assert settings.llm_base_url.host == "agentgateway"
    assert settings.unsloth_base_url.host == "host.docker.internal"
    assert settings.bazos_mcp_url is not None
    assert settings.sbazar_mcp_url is not None


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("APP_ENV", "unknown"),
        ("LOG_LEVEL", "VERBOSE"),
        ("MARKETPLACE_MODE", "unknown"),
        ("APP_PORT", "0"),
        ("APP_PORT", "65536"),
        ("APP_PORT", "not-a-port"),
        ("APP_HOST", ""),
        ("LLM_MODEL", ""),
        ("LLM_BASE_URL", "not-a-url"),
        ("AGENTGATEWAY_URL", "ftp://gateway.invalid"),
        ("BAZOS_MCP_URL", "not-a-url"),
        ("SBAZAR_MCP_URL", ""),
    ],
)
def test_invalid_configuration_is_rejected(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValidationError):
        Settings()
