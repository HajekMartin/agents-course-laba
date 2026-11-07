"""Runtime MCP discovery, LLM name mapping, validation and protocol execution."""

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass

from jsonschema import validators
from mcp.types import Tool
from pydantic import ValidationError

from marketplace_agent.domain.models import Listing, SearchRequest
from marketplace_agent.gateway_check import validate_search
from marketplace_agent.llm import AgentError

# Stage 04 target namespaces, not generated MCP tool identities.
MARKETPLACES = {"bazos": "Bazoš", "sbazar": "Sbazar"}


@dataclass(frozen=True)
class DiscoveredTool:
    llm_name: str
    mcp_name: str
    source: str
    input_schema: dict
    description: str

    @property
    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.llm_name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


class ToolRegistry:
    """Allow only discovered search tools in the configured marketplace namespaces."""

    def __init__(self, discovered: list[Tool]) -> None:
        self.tools: dict[str, DiscoveredTool] = {}
        for tool in discovered:
            match = re.fullmatch(r"(bazos|sbazar)[_./:-]+search_listings", tool.name)
            if not match:
                continue
            # OpenAI function names allow 64 ASCII letters/digits/underscores/hyphens.
            name = (
                tool.name
                if re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", tool.name)
                else ("search_" + hashlib.sha256(tool.name.encode()).hexdigest()[:24])
            )
            if name in self.tools:
                raise AgentError("Duplicate MCP tool identity; check gateway namespacing.")
            try:
                validators.validator_for(tool.inputSchema).check_schema(tool.inputSchema)
            except Exception as exc:
                raise AgentError("Invalid discovered MCP input schema.") from exc
            self.tools[name] = DiscoveredTool(
                name, tool.name, match[1], tool.inputSchema, tool.description or "Search listings."
            )

    @property
    def definitions(self) -> list[dict]:
        return [tool.definition for tool in self.tools.values()]

    @property
    def missing_sources(self) -> list[str]:
        return sorted(set(MARKETPLACES) - {tool.source for tool in self.tools.values()})

    def validate(self, name: str, arguments: str) -> tuple[DiscoveredTool, SearchRequest, dict]:
        if name not in self.tools:
            raise ValueError("Unknown or unapproved tool; use only the discovered tool names.")
        tool = self.tools[name]
        try:
            data = json.loads(arguments)
        except (ValueError, TypeError) as exc:
            raise ValueError("Tool arguments must be a JSON object.") from exc
        if not isinstance(data, dict):
            raise ValueError("Tool arguments must be a JSON object.")
        validator = validators.validator_for(tool.input_schema)(tool.input_schema)
        error = next(validator.iter_errors(data), None)
        if error:
            path = ".".join(str(part) for part in error.path) or "arguments"
            raise ValueError(f"Invalid arguments at {path} ({error.validator}); follow the schema.")
        try:
            request = SearchRequest.model_validate(data)
        except ValidationError as exc:
            details = "; ".join(error["msg"] for error in exc.errors(include_input=False))
            raise ValueError(f"Invalid search: {details}") from exc
        return tool, request, data


async def discover_tools(client: object, timeout: float) -> ToolRegistry:
    try:
        async with asyncio.timeout(timeout):
            registry = ToolRegistry(await client.list_tools())
    except AgentError:
        raise
    except Exception as exc:
        raise AgentError(
            "MCP gateway discovery failed. Check AGENTGATEWAY_URL and MCP services."
        ) from exc
    if not registry.tools:
        raise AgentError("No approved marketplace search tools discovered through agentgateway.")
    return registry


async def execute_tool(
    client: object, tool: DiscoveredTool, request: SearchRequest, arguments: dict, timeout: float
) -> dict:
    """MCP tools/call is the only execution path; failures become tool result data."""
    try:
        async with asyncio.timeout(timeout):
            result = await client.call_tool(
                tool.mcp_name, arguments, timeout=timeout, raise_on_error=False
            )
        if result.is_error:
            return {"error": "Marketplace MCP returned a tool error; check its service logs."}
        payload = result.structured_content
        if payload is None:
            # MCP permits JSON in TextContent when structuredContent is absent.
            payload = json.loads(next(item.text for item in result.content if item.type == "text"))
        validate_search(payload, request.query)
        if len(payload["listings"]) > 50:
            raise ValueError("Unbounded tool response")
        normalized = {
            "query": request.query,
            "count": payload["count"],
            "listings": [
                Listing.model_validate(item, strict=True).model_dump()
                for item in payload["listings"]
            ],
        }
        if "warning" in payload:
            normalized["warning"] = payload["warning"]
        return normalized
    except (TimeoutError, asyncio.CancelledError):
        if asyncio.current_task().cancelling():
            raise
        return {"error": "Marketplace MCP tool timed out."}
    except Exception as exc:
        # Do not forward raw upstream bodies, arguments or credentials to logs/the model.
        return {"error": f"Marketplace MCP call failed ({type(exc).__name__}); check service logs."}
