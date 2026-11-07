"""Explicit infrastructure diagnostics, without an agent or an LLM/tool loop."""

import argparse
import asyncio
import json

import httpx
from fastmcp import Client
from pydantic import ValidationError

from marketplace_agent.config import Settings
from marketplace_agent.domain.models import Listing

# Observed through tools/list on agentgateway v1.7.0, with prefixMode: always.
SEARCH_TOOLS = ("bazos_search_listings", "sbazar_search_listings")


def completion_request(model: str) -> dict:
    """Use the same bounded request for direct and gateway transport checks."""
    return {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: Hello"}],
        "max_tokens": 128,
    }


def validate_completion(payload: dict, model: str) -> None:
    """Check transport structure and model identity, without requiring exact wording."""
    if payload.get("object") != "chat.completion" or payload.get("model") != model:
        raise ValueError("Unexpected completion type or model")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Missing completion choices")
    message = choices[0].get("message", {})
    if message.get("role") != "assistant" or not isinstance(message.get("content"), str):
        raise ValueError("Invalid assistant message")


def validate_search(payload: dict, query: str) -> None:
    """Validate a gateway tool result using the existing listing contract."""
    if payload.get("query") != query or not isinstance(payload.get("listings"), list):
        raise ValueError("Invalid search response")
    if payload.get("count") != len(payload["listings"]):
        raise ValueError("Invalid listing count")
    for listing in payload["listings"]:
        Listing.model_validate(listing)
    if "warning" in payload and not isinstance(payload["warning"], str):
        raise ValueError("Invalid source warning")


def report_failure(label: str, exc: Exception) -> None:
    """Do not echo URLs, headers, upstream bodies, or credentials in error output."""
    detail = (
        f"HTTP {exc.response.status_code}"
        if isinstance(exc, httpx.HTTPStatusError)
        else (type(exc).__name__)
    )
    print(f"FAIL {label}: {detail}")


async def check_mcp(url: str, *, schemas: bool = False) -> bool:
    """Initialize, discover, inspect schemas, and invoke each tool through the gateway."""
    ok = True
    try:
        async with Client(url, timeout=20) as client:
            discovered = {tool.name: tool for tool in await client.list_tools()}
            print("OK MCP gateway: initialized and tools/list completed")
            for name in SEARCH_TOOLS:
                if name not in discovered:
                    print(f"FAIL {name}: upstream not connected or tool missing")
                    ok = False
                    continue
                try:
                    schema = discovered[name].inputSchema
                    if schema.get("required") != ["query"] or "limit" not in schema["properties"]:
                        raise ValueError("Unexpected tool schema")
                    print(f"OK {name}: upstream connected, search tool discovered")
                    if schemas:
                        print(json.dumps({"name": name, "inputSchema": schema}, sort_keys=True))
                    result = await client.call_tool(name, {"query": "notebook", "limit": 1})
                    if result.is_error:
                        raise ValueError("MCP tool error")
                    validate_search(result.structured_content, "notebook")
                    print(f"OK {name}: tools/call response validated")
                    if warning := result.structured_content.get("warning"):
                        print(f"SOURCE {name}: {warning}")
                except Exception as exc:
                    report_failure(name, exc)
                    ok = False
            if set(discovered) != set(SEARCH_TOOLS):
                print("FAIL MCP tool set: expected exactly the two marketplace search tools")
                ok = False
    except Exception as exc:
        report_failure("MCP gateway (both marketplace connections unverified)", exc)
        return False
    return ok


async def check_llm(settings: Settings, gateway_url: str, *, models_only: bool = False) -> bool:
    """Check the host API independently of the LLM route; never select/load a model."""
    headers = {}
    if key := settings.unsloth_api_key.get_secret_value():
        headers["Authorization"] = f"Bearer {key}"
    upstream = str(settings.unsloth_base_url).rstrip("/")
    ok = True
    model_available = False
    async with httpx.AsyncClient(timeout=settings.llm_timeout, trust_env=False) as client:
        try:
            response = await client.get(f"{upstream}/models", headers=headers)
            response.raise_for_status()
            models = response.json()["data"]
            print("OK Unsloth reachable: GET /models")
            for model in models:
                print(f"MODEL {model['id']} loaded={model.get('loaded', 'unknown')}")
            model_available = any(
                model["id"] == settings.unsloth_model and model.get("loaded") is not False
                for model in models
            )
        except Exception as exc:
            report_failure("Unsloth model discovery", exc)
            ok = False
        if models_only:
            return ok
        if not settings.unsloth_model or settings.unsloth_model in {
            "model-not-configured",
            "your-loaded-model-id",
        }:
            print("FAIL LLM configuration: set UNSLOTH_MODEL to a loaded MODEL id")
            return False
        if not model_available:
            print("FAIL Unsloth model: configured id is not confirmed as available")
            ok = False
        request = completion_request(settings.unsloth_model)
        for label, base, auth in (
            ("Unsloth direct chat completion", upstream, headers),
            ("LLM gateway route", gateway_url.rstrip("/"), {}),
        ):
            try:
                # Do not send an inference request for a model reported as unloaded.
                if not model_available:
                    print(f"SKIP {label}: model not confirmed loaded/available")
                    continue
                response = await client.post(f"{base}/chat/completions", json=request, headers=auth)
                response.raise_for_status()
                validate_completion(response.json(), settings.unsloth_model)
                print(f"OK {label}: model={settings.unsloth_model}")
            except Exception as exc:
                report_failure(label, exc)
                ok = False
    return ok


async def run(args: argparse.Namespace, settings: Settings) -> int:
    ok = True
    if not args.models_only:
        try:
            async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
                response = await client.get(args.ready_url)
                response.raise_for_status()
                if response.text.strip() != "ready":
                    raise ValueError("Unexpected readiness response")
                print("OK agentgateway: native readiness")
        except Exception as exc:
            report_failure("agentgateway readiness", exc)
            ok = False
        ok = (
            await check_mcp(args.mcp_url or str(settings.agentgateway_url), schemas=args.schemas)
            and ok
        )
    if not args.mcp_only:
        ok = (
            await check_llm(
                settings, args.llm_url or str(settings.llm_base_url), models_only=args.models_only
            )
            and ok
        )
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--mcp-only", action="store_true", help="Skip all LLM requests.")
    mode.add_argument(
        "--models-only", action="store_true", help="List upstream models; no inference."
    )
    parser.add_argument(
        "--schemas", action="store_true", help="Print discovered tool input schemas."
    )
    parser.add_argument("--mcp-url", help="Override the MCP gateway URL.")
    parser.add_argument("--llm-url", help="Override the LLM gateway base URL, including /v1.")
    parser.add_argument("--ready-url", default="http://agentgateway:15021/healthz/ready")
    args = parser.parse_args()
    try:
        settings = Settings()
    except ValidationError:
        print("FAIL configuration: run the offline doctor for field validation")
        return 2
    return asyncio.run(run(args, settings))


if __name__ == "__main__":
    raise SystemExit(main())
