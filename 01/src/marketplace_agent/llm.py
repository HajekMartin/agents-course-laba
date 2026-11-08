"""Small OpenAI-compatible Chat Completions client; gateway traffic only."""

from typing import Any

from openai import APIError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from smolagents import OpenAIServerModel

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


class GatewayModel(OpenAIServerModel):
    """Use the framework's native OpenAI client, with no text-to-tool fallback."""

    def generate(self, *args, **kwargs):
        try:
            message = super().generate(*args, **kwargs)
        except APIError as exc:
            status = getattr(exc, "status_code", None)
            raise AgentError(
                f"LLM gateway request failed (HTTP {status or 'unavailable'}). "
                "Check agentgateway, Unsloth, the configured model and API key."
            ) from exc
        parse_completion(message.raw.model_dump(), self.model_id)
        return message

    def parse_tool_calls(self, message):
        raise AgentError(
            "The model returned no native tool_calls. Check model tool support, "
            "its Unsloth chat template and the gateway request format."
        )


def create_model(settings: Settings) -> GatewayModel:
    if (
        not settings.llm_base_url
        or not settings.unsloth_model
        or settings.unsloth_model in {"model-not-configured", "your-loaded-model-id"}
    ):
        raise AgentError("Configure LLM_BASE_URL and the loaded UNSLOTH_MODEL in .env.")
    return GatewayModel(
        model_id=settings.unsloth_model,
        api_base=str(settings.llm_base_url),
        api_key="local-gateway",
        client_kwargs={"timeout": settings.llm_timeout, "max_retries": 0},
        retry=False,
        max_tokens=settings.agent_max_tokens,
    )
