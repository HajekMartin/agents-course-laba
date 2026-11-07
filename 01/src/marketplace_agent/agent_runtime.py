"""LangChain tools and middleware for the marketplace-specific execution rules."""

import json
from collections.abc import Callable
from dataclasses import dataclass

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from marketplace_agent.agent_tools import DiscoveredTool, ToolRegistry, execute_tool
from marketplace_agent.config import Settings
from marketplace_agent.domain.models import SearchRequest
from marketplace_agent.llm import AgentError
from marketplace_agent.results import SearchResults, model_result


class FinalAnswer(BaseModel):
    """The model may reject irrelevant ads, but cannot add or reorder factual listings."""

    model_config = ConfigDict(strict=True, extra="forbid")
    answer: str = Field(min_length=1)
    exclude_urls: list[str] = Field(default_factory=list, max_length=100)


@dataclass
class AgentTurn:
    """Mutable context belongs to one invocation, never shared across conversations."""

    results: SearchResults
    postcodes: set[str]
    model_calls: int = 0
    tool_calls: int = 0
    batch_request: SearchRequest | None = None
    format_retried: bool = False
    final: FinalAnswer | None = None


def marketplace_tools(registry: ToolRegistry, client, timeout: float) -> list[StructuredTool]:
    """Preserve discovered schemas and route every LangChain tool invocation through MCP."""

    def convert(tool: DiscoveredTool) -> StructuredTool:
        async def call(**arguments):
            request = SearchRequest.model_validate(arguments)
            payload = await execute_tool(client, tool, request, arguments, timeout)
            output = {"source": tool.source, **model_result(payload)}
            # Artifacts stay inside Python; only content is sent to the model.
            artifact = {"source": tool.source, "request": request, "payload": payload}
            return json.dumps(output, ensure_ascii=False), artifact

        return StructuredTool(
            name=tool.llm_name,
            description=tool.description,
            args_schema=tool.input_schema,
            coroutine=call,
            response_format="content_and_artifact",
        )

    return [convert(tool) for tool in registry.tools.values()]


class MarketplaceMiddleware(AgentMiddleware):
    """Validate execution and aggregate results while LangChain owns the agent loop."""

    def __init__(self, settings: Settings, registry: ToolRegistry, trace: Callable[[str], None]):
        self.settings = settings
        self.registry = registry
        self.trace = trace

    async def abefore_model(self, state, runtime):
        turn: AgentTurn = runtime.context
        if turn.model_calls >= self.settings.agent_max_iterations:
            raise AgentError(
                "Maximum agent iterations reached; no final LLM answer. "
                "Narrow the request or adjust AGENT_MAX_ITERATIONS. This turn was not saved."
            )
        turn.model_calls += 1
        self.trace(
            "[LLM] Returning tool results to model" if turn.tool_calls else "[LLM] Sending request"
        )
        # Framework tool calls may complete concurrently. Aggregate in the original
        # ToolMessage order, so source relevance and conflicting-call behavior are stable.
        batch = []
        for message in reversed(state["messages"]):
            if not isinstance(message, ToolMessage):
                break
            batch.append(message)
        for message in reversed(batch):
            if artifact := message.artifact:
                turn.results.add(artifact["source"], artifact["request"], artifact["payload"])
        if batch:
            last = batch[0]
            output = json.loads(last.content)
            output["combined"] = model_result(turn.results.combined())
            return {
                "messages": [
                    last.model_copy(update={"content": json.dumps(output, ensure_ascii=False)})
                ]
            }
        return None

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state, runtime):
        turn: AgentTurn = runtime.context
        message = state["messages"][-1]
        if not isinstance(message, AIMessage) or message.invalid_tool_calls:
            raise AgentError("Malformed native LLM tool call; no invalid call was executed.")
        calls = message.tool_calls
        if calls:
            if len(calls) > self.settings.agent_max_tool_calls:
                raise AgentError(
                    "LLM requested too many tool calls in one response; none executed."
                )
            turn.tool_calls += len(calls)
            turn.batch_request = None
            for call in calls:
                try:
                    _, request, _ = self.registry.validate(call["name"], json.dumps(call["args"]))
                except ValueError:
                    continue
                turn.batch_request = request
                break
            return None
        try:
            final = FinalAnswer.model_validate_json(message.content)
        except ValidationError as exc:
            if turn.format_retried:
                raise AgentError(
                    "LLM final response did not follow the answer/exclude_urls JSON format. "
                    "Check the model's instruction following; no results were displayed."
                ) from exc
            turn.format_retried = True
            self.trace("[LLM] Final format invalid; requesting one formatting correction")
            return {
                "messages": [
                    HumanMessage(
                        content=(
                            'Formatting correction only: return JSON with "answer" '
                            '(brief text in the original user language) and "exclude_urls" '
                            "(array of retrieved irrelevant listing URLs, or []). "
                            "No Markdown fences, extra keys or tool calls. Preserve source "
                            "warnings; unavailable sources do not establish no matches."
                        )
                    )
                ],
                "jump_to": "model",
            }
        known_urls = {
            listing["url"]
            for payload in turn.results.responses.values()
            for listing in payload.get("listings", [])
        }
        if set(final.exclude_urls) - known_urls:
            raise AgentError("LLM attempted to exclude unknown listing URLs.")
        turn.final = final
        self.trace("[LLM] Final response generated")
        return None

    async def awrap_tool_call(self, request, handler):
        turn: AgentTurn = request.runtime.context
        call = request.tool_call
        self.trace(f"[LLM] Requested tool: {call['name']}")
        try:
            tool, search, _ = self.registry.validate(call["name"], json.dumps(call["args"]))
            if search.location and search.location not in turn.postcodes:
                raise ValueError(
                    "The user did not supply this postcode. Ask for an explicit PSČ "
                    "or a standalone postcode; do not infer it from a town or drop geography."
                )
            if search != turn.batch_request:
                raise ValueError("Use identical filters/query/sort/limit for both sources.")
        except ValueError as exc:
            self.trace("[MCP] Rejected invalid tool name or arguments; no call executed")
            return ToolMessage(
                content=json.dumps({"error": str(exc)}),
                tool_call_id=call["id"],
                name=call["name"],
                status="error",
            )
        self.trace(f"[MCP] Executing {tool.mcp_name} through agentgateway")
        result = await handler(request)
        payload = result.artifact["payload"]
        self.trace(
            "[MCP] Tool failed"
            if "error" in payload
            else f"[MCP] Received {len(payload['listings'])} listings"
        )
        return result
