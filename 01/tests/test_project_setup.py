"""Verify initialization without any external service or internet connection."""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from http.client import HTTPConnection
from importlib.metadata import distribution, version
from pathlib import Path

import pytest
from pydantic import ValidationError

import marketplace_agent
from marketplace_agent.cli import main
from marketplace_agent.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep host configuration and developer .env files out of all tests."""
    for key in tuple(os.environ):
        if key.lower() in Settings.model_fields:
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "marketplace_agent", *arguments],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_package_is_installed_and_importable() -> None:
    assert marketplace_agent.APP_NAME == "Marketplace AI Agent"
    assert marketplace_agent.__version__ == version("marketplace-agent")
    entry_points = distribution("marketplace-agent").entry_points
    entry_point = next(item for item in entry_points if item.name == "marketplace-agent")
    assert entry_point.load() is main


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


def test_help_describes_available_commands_and_implementation_status() -> None:
    result = run_cli("--help")
    assert result.returncode == 0
    for command in ("version", "doctor", "serve"):
        assert command in result.stdout
    assert "not implemented yet" in " ".join(result.stdout.split())


def test_version_works_even_with_invalid_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PORT", "invalid")
    result = run_cli("version")
    assert result.returncode == 0
    assert result.stdout.strip() == f"Marketplace AI Agent {marketplace_agent.__version__}"


def test_doctor_succeeds_without_future_services() -> None:
    result = run_cli("doctor")
    assert result.returncode == 0
    assert "OK configuration" in result.stdout
    assert "OK Python" in result.stdout
    assert "OK package" in result.stdout
    assert "not checked at this stage" in result.stdout
    assert "not implemented yet" in result.stdout


def test_doctor_accepts_unreachable_future_service_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in ("LLM_BASE_URL", "AGENTGATEWAY_URL", "BAZOS_MCP_URL", "SBAZAR_MCP_URL"):
        monkeypatch.setenv(variable, "http://127.0.0.1:1/unavailable")
    result = run_cli("doctor")
    assert result.returncode == 0


@pytest.mark.parametrize("command", ["doctor", "serve"])
def test_cli_reports_configuration_errors_without_echoing_values(
    monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "private-invalid-value")
    result = run_cli(command)
    assert result.returncode == 2
    assert "Invalid application configuration" in result.stderr
    assert "log_level" in result.stderr
    assert "private-invalid-value" not in result.stderr
    assert "Traceback" not in result.stderr


def test_unknown_command_fails() -> None:
    result = run_cli("search")
    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_server_reports_port_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        monkeypatch.setenv("APP_HOST", "127.0.0.1")
        monkeypatch.setenv("APP_PORT", str(listener.getsockname()[1]))
        result = run_cli("serve")
    assert result.returncode == 1
    assert "Could not start the health server" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("shutdown_signal", [signal.SIGTERM, signal.SIGINT])
def test_server_starts_serves_health_and_shuts_down(
    monkeypatch: pytest.MonkeyPatch, shutdown_signal: signal.Signals
) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    monkeypatch.setenv("APP_HOST", "127.0.0.1")
    monkeypatch.setenv("APP_PORT", str(port))
    process = subprocess.Popen(
        [sys.executable, "-m", "marketplace_agent", "serve"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while True:
            connection = HTTPConnection("127.0.0.1", port, timeout=0.5)
            try:
                connection.request("GET", "/health")
                response = connection.getresponse()
                payload = json.loads(response.read())
                assert response.status == 200
                assert response.getheader("Content-Type") == "application/json"
                assert payload == {
                    "status": "ok",
                    "application": marketplace_agent.APP_NAME,
                    "version": marketplace_agent.__version__,
                }
                break
            except OSError:
                if process.poll() is not None or time.monotonic() >= deadline:
                    pytest.fail("Health server failed to become ready")
                time.sleep(0.05)
            finally:
                connection.close()

        connection = HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            connection.request("GET", "/missing")
            response = connection.getresponse()
            assert response.status == 404
            response.read()
        finally:
            connection.close()

        process.send_signal(shutdown_signal)
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, stdout + stderr
        assert "Health server stopped" in stderr
        assert "not implemented yet" in stderr
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)
