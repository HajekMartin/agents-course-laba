"""Small OpenAI-compatible Chat Completions client; gateway traffic only."""

import asyncio
import json
from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, convert_to_openai_messages
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from marketplace_agent.config import Settings


class AgentError(RuntimeError):
    """An actionable diagnostic safe to display without upstream bodies or secrets."""


class ToolCallFunction(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    name: str = Field(min_length=1, max_length=256)
    arguments: str = Field(max_length=16000)


class ToolCall(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    id: str = Field(min_length=1, max_length=256)
    type: str
    function: ToolCallFunction


def parse_completion(payload: Any, model: str) -> dict:
    """Accept native tool_calls only; never extract executable calls from model text."""
    try:
        if payload["model"] != model:
            raise ValueError("Wrong model")
        choice = payload["choices"][0]
        if not isinstance(choice, dict):
            raise ValueError("Invalid completion choice")
        if choice.get("finish_reason") in {"length", "content_filter"}:
            raise AgentError(
                "LLM response was truncated or blocked. Check the model/chat template or "
                "increase AGENT_MAX_TOKENS; no partial tool call was executed."
            )
        message = choice["message"]
        if not isinstance(message, dict):
            raise ValueError("Invalid assistant message")
        if message["role"] != "assistant" or message.get("function_call"):
            raise ValueError("Expected native assistant response")
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise ValueError("Invalid content")
        calls = message.get("tool_calls")
        if calls is None:
            calls = []
        if not isinstance(calls, list):
            raise ValueError("Invalid tool_calls")
        parsed = [ToolCall.model_validate(call) for call in calls]
        if any(call.type != "function" for call in parsed):
            raise ValueError("Unsupported tool type")
        if len({call.id for call in parsed}) != len(parsed):
            raise ValueError("Duplicate tool call ids")
        if choice.get("finish_reason") == "tool_calls" and not parsed:
            raise ValueError("Missing tool_calls")
        if not parsed and not (content and content.strip()):
            raise ValueError("Empty response")
        result = {"role": "assistant", "content": content}
        if parsed:
            result["tool_calls"] = [call.model_dump() for call in parsed]
        return result
    except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
        raise AgentError(
            "Malformed LLM response or native tool call. Check the model's tool-calling "
            "support, Unsloth chat template and gateway Chat Completions format."
        ) from exc


class GatewayLLM:
    """Use the existing Stage 04 model and LLM_BASE_URL; never contact Unsloth directly."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        if not settings.llm_base_url:
            raise AgentError("Set LLM_BASE_URL to the agentgateway LLM endpoint, including /v1.")
        if not settings.unsloth_model or settings.unsloth_model in {
            "your-loaded-model-id",
            "model-not-configured",
        }:
            raise AgentError("Set UNSLOTH_MODEL to the loaded model ID already routed by Stage 04.")
        self.settings = settings
        self.client = client
        self.base_url = str(settings.llm_base_url).rstrip("/")
        self.model = settings.unsloth_model

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        try:
            async with asyncio.timeout(self.settings.llm_timeout):
                response = await self.client.request(method, self.base_url + path, **kwargs)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object")
                return payload
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = {
                400: "request/tools rejected; check native tool support and the chat template",
                401: "upstream authentication failed; check UNSLOTH_API_KEY on the gateway",
                404: "model or route missing; check UNSLOTH_MODEL and the gateway /v1 URL",
                422: "request/tools rejected; check the model, chat template and request format",
                503: "Unsloth upstream unavailable; start its API and load the configured model",
                504: "Unsloth timed out; check the loaded model and LLM_TIMEOUT",
            }.get(status, "gateway or Unsloth request failed; inspect service logs")
            raise AgentError(f"LLM gateway HTTP {status}: {detail}.") from exc
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise AgentError("LLM gateway timed out. Check Unsloth and LLM_TIMEOUT.") from exc
        except httpx.RequestError as exc:
            raise AgentError(
                "LLM gateway unavailable. Check LLM_BASE_URL and agentgateway."
            ) from exc
        except ValueError as exc:
            raise AgentError(
                "LLM gateway returned invalid JSON; check the endpoint format."
            ) from exc

    async def complete(
        self, messages: list[dict], tools: list[dict], *, tool_choice: str = "auto"
    ) -> dict:
        request = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.settings.agent_max_tokens,
        }
        if tools:
            request.update(tools=tools, tool_choice=tool_choice)
        return parse_completion(
            await self._request("POST", "/chat/completions", json=request), self.model
        )

    async def check_connection(self) -> None:
        """The gateway catalog alone does not establish that the host model is loaded."""
        catalog = await self._request("GET", "/models")
        models = catalog.get("data")
        if not isinstance(models, list) or any(not isinstance(item, dict) for item in models):
            raise AgentError("LLM gateway returned a malformed model catalog.")
        if not any(item.get("id") == self.model for item in models):
            raise AgentError("UNSLOTH_MODEL is absent from the gateway model catalog.")

    async def probe_tools(self, registry: Any) -> None:
        """Request and validate a native call, discard it, and never execute a probe search."""
        message = await self.complete(
            [
                {
                    "role": "user",
                    "content": (
                        "Protocol capability test only. Request one provided search tool "
                        "with query "
                        "'notebook' and limit 1 using native tool calling. Do not answer in prose. "
                        "The application will validate but will not execute this probe."
                    ),
                }
            ],
            registry.definitions,
            tool_choice="required",
        )
        calls = message.get("tool_calls", [])
        if not calls:
            raise AgentError(
                "Native tool-calling probe failed: LLM returned text instead of tool_calls. "
                "HTTP transport works, but model/tool parser/chat-template support is not "
                "confirmed. No marketplace search was executed."
            )
        try:
            for call in calls:
                registry.validate(call["function"]["name"], call["function"]["arguments"])
        except ValueError as exc:
            raise AgentError(
                "Native tool-calling probe returned invalid names or arguments. Check the "
                "model, Unsloth tool parser/chat template and gateway request format."
            ) from exc


class GatewayChatModel(BaseChatModel):
    """LangChain model adapter reusing the validated gateway-only HTTP transport."""

    gateway: Any = Field(exclude=True, repr=False)

    @property
    def _llm_type(self) -> str:
        return "marketplace-agentgateway"

    def bind_tools(self, tools, *, tool_choice: str | None = None, **kwargs):
        return self.bind(
            tools=[convert_to_openai_tool(tool) for tool in tools],
            tool_choice=tool_choice or "auto",
            **kwargs,
        )

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError("The gateway model supports async ainvoke only.")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        response = await self.gateway.complete(
            convert_to_openai_messages(messages),
            kwargs.get("tools", []),
            tool_choice=kwargs.get("tool_choice", "auto"),
        )
        calls = response.get("tool_calls", [])
        try:
            parsed = [
                {
                    "id": call["id"],
                    "name": call["function"]["name"],
                    "args": json.loads(call["function"]["arguments"]),
                    "type": "tool_call",
                }
                for call in calls
            ]
            if any(not isinstance(call["args"], dict) for call in parsed):
                raise ValueError("Arguments must be objects")
        except (ValueError, TypeError) as exc:
            raise AgentError("Malformed native tool arguments; expected JSON objects.") from exc
        message = AIMessage(content=response.get("content") or "", tool_calls=parsed)
        return ChatResult(generations=[ChatGeneration(message=message)])
