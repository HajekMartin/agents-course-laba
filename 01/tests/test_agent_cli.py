"""CLI lifecycle and safe diagnostics independent of external services."""

import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.types import Tool

from marketplace_agent.agent import AgentReply
from marketplace_agent.cli import main
from marketplace_agent.config import Settings
from marketplace_agent.domain.models import SearchRequest
from marketplace_agent.llm import AgentError


@pytest.fixture(autouse=True)
def configuration(monkeypatch, tmp_path):
    for key in tuple(os.environ):
        if key.lower() in Settings.model_fields:
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENTGATEWAY_URL", "http://gateway.test:3000/mcp")
    monkeypatch.setenv("LLM_BASE_URL", "http://gateway.test:3001/v1")
    monkeypatch.setenv("UNSLOTH_MODEL", "cli-test-model")


def test_search_really_calls_agent_and_prints_trace(monkeypatch, capsys):
    from marketplace_agent import agent

    ask = AsyncMock(return_value=AgentReply("Výsledek modelu.", {}))

    @asynccontextmanager
    async def connect(settings, trace):
        assert settings.unsloth_model == "cli-test-model"
        trace("[LLM] test execution trace")
        yield SimpleNamespace(ask=ask)

    monkeypatch.setattr(agent, "connect_agent", connect)
    assert main(["search", "iPhone 15 do 12000 Kč", "--verbose"]) == 0
    ask.assert_awaited_once_with("iPhone 15 do 12000 Kč")
    output = capsys.readouterr()
    assert "Výsledek modelu" in output.out
    assert "[LLM] test execution trace" in output.err


def test_chat_clear_quit_and_per_turn_error(monkeypatch, capsys):
    from marketplace_agent import agent

    replies = iter(["hello", "clear", "fail", "next", "quit"])
    calls = []
    session = SimpleNamespace(clear=lambda: calls.append("clear"))

    async def ask(text):
        calls.append(text)
        if text == "fail":
            raise AgentError("expected failure")
        return AgentReply("Odpověď modelu.", {})

    session.ask = ask

    @asynccontextmanager
    async def connect(*args):
        yield session

    monkeypatch.setattr(agent, "connect_agent", connect)
    monkeypatch.setattr("builtins.input", lambda _: next(replies))
    assert main(["chat"]) == 0
    assert calls == ["hello", "clear", "fail", "next"]
    assert "expected failure" in capsys.readouterr().err


def test_incomplete_search_displays_authoritative_diagnostics_over_model_narrative(
    monkeypatch, capsys
):
    from marketplace_agent import agent

    @asynccontextmanager
    async def connect(*args):
        yield SimpleNamespace(
            ask=AsyncMock(
                return_value=AgentReply(
                    "Misleading model narrative.",
                    {
                        "incomplete": True,
                        "listings": [],
                        "warnings": ["Bazoš: source access disabled."],
                        "search": {},
                    },
                )
            )
        )

    monkeypatch.setattr(agent, "connect_agent", connect)
    assert main(["search", "iPhone"]) == 0
    output = capsys.readouterr().out
    assert "Misleading" not in output
    assert "source access disabled" in output
    assert "incomplete" in output


def test_cli_unavailable_agent_has_no_traceback(monkeypatch, capsys):
    from marketplace_agent import agent

    @asynccontextmanager
    async def connect(*args):
        raise AgentError("Unsloth unavailable")
        yield  # pragma: no cover - makes this an async context manager

    monkeypatch.setattr(agent, "connect_agent", connect)
    assert main(["search", "notebook"]) == 1
    output = capsys.readouterr()
    assert "Unsloth unavailable" in output.err
    assert "Traceback" not in output.err


def test_tools_requires_no_model_and_uses_mcp_discovery(monkeypatch, capsys):
    monkeypatch.delenv("UNSLOTH_MODEL")

    class FakeClient:
        def __init__(self, url, **kwargs):
            assert url == "http://gateway.test:3000/mcp"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def list_tools(self):
            return [
                Tool(name="bazos_search_listings", inputSchema=SearchRequest.model_json_schema())
            ]

    monkeypatch.setattr("fastmcp.Client", FakeClient)
    assert main(["tools"]) == 0
    output = capsys.readouterr().out
    assert "MCP bazos_search_listings" in output
    assert "Sbazar search tool unavailable" in output


def test_online_doctor_checks_llm_even_when_mcp_fails(monkeypatch, capsys):
    from marketplace_agent import llm

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise OSError("private credentials")

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr("fastmcp.Client", FakeClient)
    check = AsyncMock()
    complete = AsyncMock(return_value={"role": "assistant", "content": "Hello"})
    monkeypatch.setattr(llm.GatewayLLM, "check_connection", check)
    monkeypatch.setattr(llm.GatewayLLM, "complete", complete)
    assert main(["doctor"]) == 1
    check.assert_awaited_once()
    complete.assert_awaited_once()
    output = capsys.readouterr().out
    assert "FAIL MCP" in output and "OK Unsloth through gateway" in output
    assert "private credentials" not in output
