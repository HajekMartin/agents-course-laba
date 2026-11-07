"""Command line diagnostics, one-shot agent search and in-memory interactive chat."""

import argparse
import asyncio
import logging
import platform
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from marketplace_agent import APP_NAME, __version__
from marketplace_agent.config import Settings
from marketplace_agent.health import serve

FEATURE_STATUS = (
    "Bazos and Sbazar MCP search run as separate services; live access is restricted. "
    "agentgateway connects both MCP servers and an external Unsloth API. "
    "The LangChain agent uses native LLM tool calling through agentgateway."
)


def _doctor(settings: Settings) -> int:
    """Check local initialization independently of service availability."""
    print(f"OK configuration: environment={settings.app_env}, mode={settings.marketplace_mode}")
    if sys.version_info < (3, 12):  # noqa: UP036 - doctor explicitly checks the runtime.
        print(
            f"ERROR Python {platform.python_version()}: Python 3.12+ is required.", file=sys.stderr
        )
        return 1
    print(f"OK Python {platform.python_version()}")
    print(f"OK package: {APP_NAME} {__version__}")
    print("Local configuration checks passed.")
    print(FEATURE_STATUS)
    return 0


async def _online_doctor(settings: Settings) -> int:
    """Check services independently; an unavailable source does not hide other diagnostics."""
    import httpx
    from fastmcp import Client

    from marketplace_agent.agent_tools import MARKETPLACES, discover_tools
    from marketplace_agent.llm import AgentError, GatewayLLM

    registry = None
    ok = True
    try:
        if not settings.agentgateway_url:
            raise AgentError("Set AGENTGATEWAY_URL to the MCP gateway URL.")
        async with Client(
            str(settings.agentgateway_url),
            timeout=settings.mcp_timeout,
            init_timeout=settings.mcp_timeout,
        ) as client:
            registry = await discover_tools(client, settings.mcp_timeout)
            print("OK MCP gateway: initialization and tool discovery")
            for source, label in MARKETPLACES.items():
                available = source not in registry.missing_sources
                print(
                    f"{'FAIL' if not available else 'OK'} {label}: "
                    f"{'search tool missing' if not available else 'search tool available'}"
                )
                ok = available and ok
    except Exception as exc:
        detail = str(exc) if isinstance(exc, AgentError) else type(exc).__name__
        print(f"FAIL MCP gateway/Bazoš/Sbazar: {detail}")
        ok = False
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout, trust_env=False) as http:
            llm = GatewayLLM(settings, http)
            await llm.check_connection()
            print("OK LLM gateway: configured model route")
            if registry:
                await llm.probe_tools(registry)
                print("OK Unsloth through gateway: native tool-calling probe (not executed)")
            else:
                await llm.complete([{"role": "user", "content": "Reply with exactly: Hello"}], [])
                print("OK Unsloth through gateway: completion; native tools unverified without MCP")
    except AgentError as exc:
        print(f"FAIL LLM/Unsloth through gateway: {exc}")
        ok = False
    return 0 if ok else 1


async def _agent_command(args: argparse.Namespace, settings: Settings) -> int:
    from fastmcp import Client

    from marketplace_agent.agent import connect_agent
    from marketplace_agent.agent_tools import MARKETPLACES, discover_tools
    from marketplace_agent.llm import AgentError
    from marketplace_agent.results import render_results

    if args.command == "tools":
        if not settings.agentgateway_url:
            raise AgentError("Set AGENTGATEWAY_URL to the MCP gateway URL.")
        try:
            async with Client(
                str(settings.agentgateway_url),
                timeout=settings.mcp_timeout,
                init_timeout=settings.mcp_timeout,
            ) as client:
                registry = await discover_tools(client, settings.mcp_timeout)
                for tool in registry.tools.values():
                    print(f"{tool.llm_name} -> MCP {tool.mcp_name} ({MARKETPLACES[tool.source]})")
                    print(f"  {tool.description}")
                for source in registry.missing_sources:
                    print(f"WARNING: {MARKETPLACES[source]} search tool unavailable.")
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError(
                "MCP gateway unavailable; check AGENTGATEWAY_URL and services."
            ) from exc
        return 0

    trace = (lambda line: print(line, file=sys.stderr)) if args.verbose else None
    async with connect_agent(settings, trace) as agent:
        if args.command == "search":
            reply = await agent.ask(args.query)
            if not reply.results.get("incomplete"):
                print(reply.text)
            if rendered := render_results(reply.results):
                print(rendered)
            return 0
        print("Marketplace chat. Commands: exit, quit, clear.")
        while True:
            try:
                text = await asyncio.to_thread(input, "You> ")
            except EOFError:
                return 0
            if text.strip().lower() in {"exit", "quit"}:
                return 0
            if text.strip().lower() == "clear":
                agent.clear()
                print("Conversation cleared.")
                continue
            if not text.strip():
                continue
            try:
                reply = await agent.ask(text)
                if not reply.results.get("incomplete"):
                    print(f"Agent> {reply.text}")
                if rendered := render_results(reply.results):
                    print(rendered)
            except AgentError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """Run a CLI command and return its exit status."""
    parser = argparse.ArgumentParser(
        prog="marketplace-agent", description=APP_NAME, epilog=FEATURE_STATUS
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("version", help="Display the application name and version.")
    doctor = commands.add_parser(
        "doctor", help="Validate configuration and gateway/LLM/MCP connections."
    )
    doctor.add_argument("--offline", action="store_true", help="Check local configuration only.")
    commands.add_parser("serve", help="Run the development health endpoint.")
    commands.add_parser("tools", help="List approved MCP tools discovered through agentgateway.")
    chat = commands.add_parser("chat", help="Start interactive agent chat.")
    search = commands.add_parser("search", help="Search through the LLM agent and MCP tools.")
    search.add_argument("query", help="Natural-language search request.")
    for command in (chat, search):
        command.add_argument(
            "--verbose", action="store_true", help="Trace actual LLM/MCP execution."
        )
    args = parser.parse_args(argv)

    if args.command == "version":
        print(f"{APP_NAME} {__version__}")
        return 0

    try:
        settings = Settings()
    except ValidationError as exc:
        print("Invalid application configuration:", file=sys.stderr)
        for error in exc.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in error["loc"])
            print(f"  {location}: {error['msg']}", file=sys.stderr)
        return 2

    if args.command == "doctor":
        result = _doctor(settings)
        return result if result or args.offline else asyncio.run(_online_doctor(settings))

    if args.command in {"chat", "search", "tools"}:
        from marketplace_agent.llm import AgentError

        try:
            return asyncio.run(_agent_command(args, settings))
        except AgentError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("\nSession ended.")
            return 0

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger(__name__).info(FEATURE_STATUS)
    try:
        serve(settings)
    except OSError as exc:
        print(f"Could not start the health server: {exc}", file=sys.stderr)
        return 1
    return 0
