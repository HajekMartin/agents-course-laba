"""Offline tests of the real smolagents loop, native model responses and MCP wrappers."""

import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastmcp import Client
from mcp.types import Tool
from openai.types.chat import ChatCompletion
from smolagents import Model, ToolCallingAgent
from smolagents.default_tools import FinalAnswerTool
from smolagents.memory import TaskStep
from smolagents.models import ChatMessage, ChatMessageToolCall, ChatMessageToolCallFunction

from marketplace_agent import agent as agent_module
from marketplace_agent.agent import MarketplaceAgent, requested_sources, supplied_postcodes
from marketplace_agent.agent_tools import ToolRegistry, discover_tools, execute_tool
from marketplace_agent.config import Settings
from marketplace_agent.llm import AgentError, GatewayModel, parse_completion
from marketplace_agent.mcp.bazos_server import mcp as bazos_mcp

MODEL = "offline-test-model"


def settings(**kwargs):
    return Settings(
        _env_file=None,
        llm_base_url="http://gateway.test:3001/v1",
        agentgateway_url="http://gateway.test:3000/mcp",
        unsloth_model=MODEL,
        **kwargs,
    )


@pytest.fixture
def registry():
    async def original():
        async with Client(bazos_mcp) as client:
            return (await client.list_tools())[0]

    tool = asyncio.run(original())
    return ToolRegistry(
        [
            tool.model_copy(update={"name": f"{source}_search_listings"})
            for source in ("bazos", "sbazar")
        ]
    )


def native(name="bazos_search_listings", args=None, call_id="1"):
    return ChatMessageToolCall(
        id=call_id,
        type="function",
        function=ChatMessageToolCallFunction(
            name=name,
            arguments=args if args is not None else {"query": "iPhone 15", "max_price": 12000},
        ),
    )


def final(answer="Results below.", exclude=None):
    args = {"answer": answer, "exclude_urls": exclude or []}
    return [native("final_answer", args)]


class FakeModel(Model):
    def __init__(self, *responses):
        super().__init__(model_id=MODEL)
        self.responses = list(responses)
        self.requests = []
        self.available_tools = []

    def generate(self, messages, **kwargs):
        self.requests.append(copy.deepcopy(messages))
        self.available_tools.append([tool.name for tool in kwargs.get("tools_to_call_from", [])])
        calls = self.responses.pop(0)
        if isinstance(calls, str):
            return ChatMessage(role="assistant", content=calls, tool_calls=[])
        return ChatMessage(role="assistant", content="", tool_calls=calls)


def listing(price=10000, url="https://mobil.bazos.cz/inzerat/1/iphone.php", **kwargs):
    return {
        "title": "iPhone 15",
        "price": price,
        "currency": "CZK",
        "location": "Liberec",
        "url": url,
        "description": None,
        **kwargs,
    }


def payload(*items, warning=None, query="iPhone 15"):
    result = {"query": query, "count": len(items), "listings": list(items)}
    if warning:
        result["warning"] = warning
    return result


@pytest.fixture
def build_agent(monkeypatch, registry):
    async def discover(_):
        return registry

    monkeypatch.setattr(agent_module, "discover_gateway", discover)

    def build(responses, tool_results, **options):
        calls = []
        results = iter(tool_results)

        def execute(settings, tool, request, arguments):
            calls.append((tool.mcp_name, copy.deepcopy(arguments)))
            return next(results)

        monkeypatch.setattr(agent_module, "call_gateway", execute)
        model = FakeModel(*responses)
        return MarketplaceAgent(settings(**options), model=model), model, calls

    return build


def test_discovery_schema_and_only_approved_names(registry):
    tools = [Tool(name=t.mcp_name, inputSchema=t.input_schema) for t in registry.tools.values()]
    tools.append(Tool(name="delete_all", inputSchema={"type": "object"}))
    client = SimpleNamespace(list_tools=AsyncMock(return_value=tools))
    result = asyncio.run(discover_tools(client, 1))
    assert set(result.tools) == {"bazos_search_listings", "sbazar_search_listings"}
    assert not result.missing_sources
    for definition in result.definitions:
        tool = result.tools[definition["function"]["name"]]
        assert definition["function"]["parameters"] == tool.input_schema


def test_aliases_preserve_actual_mcp_identity(registry):
    schema = next(iter(registry.tools.values())).input_schema
    mapped = ToolRegistry(
        [
            Tool(name=name, inputSchema=schema)
            for name in (
                "bazos/search_listings",
                "bazos-search_listings",
                "sbazar__search_listings",
            )
        ]
    )
    assert len(mapped.tools) == 3
    for tool in mapped.tools.values():
        assert tool.llm_name.isidentifier()
        validated, _, _ = mapped.validate(tool.llm_name, '{"query":"test"}')
        assert validated.mcp_name == tool.mcp_name


@pytest.mark.parametrize(
    "data",
    [
        "{",
        "[]",
        "null",
        "{}",
        '{"query":""}',
        '{"query":"test","limit":true}',
        '{"query":"test","limit":51}',
        '{"query":"test","max_pages":6}',
        '{"query":"test","min_price":-1}',
        '{"query":"test","max_price":"12000"}',
        '{"query":"test","radius_km":30}',
        '{"query":"test","location":"Liberec"}',
        '{"query":"test","min_price":100,"max_price":99}',
        '{"query":"test","sort_by":"random"}',
        '{"query":"test","unexpected":true}',
    ],
)
def test_invalid_arguments(registry, data):
    with pytest.raises(ValueError):
        registry.validate("bazos_search_listings", data)


def test_unknown_and_missing_tools(registry):
    with pytest.raises(ValueError, match="unapproved"):
        registry.validate("invented", '{"query":"test"}')
    with pytest.raises(AgentError, match="No approved"):
        asyncio.run(discover_tools(SimpleNamespace(list_tools=AsyncMock(return_value=[])), 1))
    tool = Tool(name="bazos_search_listings", inputSchema={"type": "object"})
    with pytest.raises(AgentError, match="Duplicate"):
        ToolRegistry([tool, tool])


def completion(message, reason="stop"):
    return {"model": MODEL, "choices": [{"message": message, "finish_reason": reason}]}


@pytest.mark.parametrize(
    "message",
    [
        {},
        {"role": "user", "content": "wrong role"},
        {"role": "assistant", "content": None},
        {"role": "assistant", "tool_calls": [{}]},
        {"role": "assistant", "function_call": {"name": "legacy"}},
    ],
)
def test_malformed_model_responses(message):
    with pytest.raises(AgentError):
        parse_completion(completion(message), MODEL)


def test_native_call_parsing_and_truncated_output():
    call = {
        "id": "1",
        "type": "function",
        "function": {"name": "bazos_search_listings", "arguments": '{"query":"iPhone"}'},
    }
    message = {"role": "assistant", "content": None, "tool_calls": [call]}
    assert parse_completion(completion(message, "tool_calls"), MODEL) == message
    with pytest.raises(AgentError, match="truncated"):
        parse_completion(completion(message, "length"), MODEL)
    with pytest.raises(AgentError, match="Malformed"):
        parse_completion(completion({**message, "tool_calls": [call, call]}), MODEL)


def test_native_model_never_parses_prose_into_a_tool_call():
    model = GatewayModel(model_id=MODEL, api_base="http://gateway.test/v1", api_key="unused")
    try:
        with pytest.raises(AgentError, match="no native"):
            model.parse_tool_calls(
                ChatMessage(role="assistant", content='{"name":"search_listings"}')
            )
    finally:
        model.client.close()


@pytest.mark.parametrize("final_only", [False, True])
def test_gateway_requests_native_calls_without_text_action_stop_markers(final_only):
    client = Mock()
    client.chat.completions.create.return_value = ChatCompletion.model_validate(
        {
            "id": "test-completion",
            "object": "chat.completion",
            "created": 0,
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "final",
                                "type": "function",
                                "function": {
                                    "name": "final_answer",
                                    "arguments": '{"answer":"Done."}',
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )
    model = GatewayModel(model_id=MODEL, client=client, retry=False)
    tools = [FinalAnswerTool()]
    if not final_only:
        tools.append(agent_module.PostcodeLookup())
    model.generate(
        [ChatMessage(role="user", content="Search.")],
        tools_to_call_from=tools,
        stop_sequences=["Observation:", "Calling tools:"],
    )
    request = client.chat.completions.create.call_args.kwargs
    assert "stop" not in request
    assert request["tool_choice"] == (
        {"type": "function", "function": {"name": "final_answer"}} if final_only else "required"
    )


def test_mcp_execution_uses_the_discovered_identity(registry):
    tool, request, args = registry.validate("bazos_search_listings", '{"query":"iPhone 15"}')
    client = SimpleNamespace(
        call_tool=AsyncMock(
            return_value=SimpleNamespace(is_error=False, structured_content=payload(listing()))
        )
    )
    result = asyncio.run(execute_tool(client, tool, request, args, 2))
    assert result["count"] == 1
    client.call_tool.assert_awaited_once_with(tool.mcp_name, args, timeout=2, raise_on_error=False)


def test_mcp_coverage_counts_are_returned_to_the_model(registry):
    tool, request, args = registry.validate("bazos_search_listings", '{"query":"iPhone 15"}')
    data = payload(listing()) | {
        "pages_scanned": 2,
        "scanned_count": 80,
        "filtered_count": 60,
        "has_more": True,
    }
    client = SimpleNamespace(
        call_tool=AsyncMock(
            return_value=SimpleNamespace(
                is_error=False,
                structured_content=data,
            )
        )
    )
    result = asyncio.run(execute_tool(client, tool, request, args, 2))
    assert result["pages_scanned"] == 2 and result["filtered_count"] == 60
    assert result["has_more"] is True


@pytest.mark.parametrize("error", [TimeoutError(), OSError("private body")])
def test_mcp_errors_are_tool_data(registry, error):
    tool, request, args = registry.validate("bazos_search_listings", '{"query":"iPhone 15"}')
    client = SimpleNamespace(call_tool=AsyncMock(side_effect=error))
    result = asyncio.run(execute_tool(client, tool, request, args, 1))
    assert "error" in result
    assert "private body" not in result["error"]


def test_real_smolagents_loop_calls_both_sources_and_returns_results_to_model(build_agent):
    agent, model, calls = build_agent(
        [[native(), native("sbazar_search_listings", call_id="2")], final()],
        [payload(listing()), payload(listing(9000, "https://www.sbazar.cz/inzerat/2-phone"))],
    )
    answer = agent.run("Najdi iPhone 15 do 12000 Kč.")
    assert isinstance(agent, ToolCallingAgent)
    assert [name for name, _ in calls] == ["bazos_search_listings", "sbazar_search_listings"]
    assert agent.last_results["count"] == 2
    assert "https://www.sbazar.cz/inzerat/2-phone" in answer
    observation = str(model.requests[1])
    assert "9000" in observation and "combined" in observation
    assert agent.tool_call_count == 2


@pytest.mark.parametrize(
    ("sort", "expected"), [("price_asc", [9000, 10000]), ("price_desc", [12000, 11000])]
)
def test_global_price_range_sort_limit_and_duplicates(build_agent, sort, expected):
    args = {
        "query": "iPhone 15",
        "min_price": 9000,
        "max_price": 12000,
        "sort_by": sort,
        "limit": 2,
    }
    item = listing(11000, "a")
    agent, _, _ = build_agent(
        [[native(args=args), native("sbazar_search_listings", args, "2")], final()],
        [
            payload(item, listing(10000, "b"), item),
            payload(
                listing(9000, "c"), listing(12000, "d"), listing(13000, "e"), listing(None, "f")
            ),
        ],
    )
    agent.run("Search both sources.")
    assert [item["price"] for item in agent.last_results["listings"]] == expected


def test_sequential_calls_and_explicit_single_source(build_agent):
    agent, _, calls = build_agent(
        [[native()], [native("sbazar_search_listings", call_id="2")], final()],
        [payload(listing()), payload()],
    )
    agent.run("Prohledej oba bazary.")
    assert len(calls) == 2
    assert agent.last_results["searched_sources"] == ["Bazoš", "Sbazar"]


def test_completed_sources_leave_only_native_final_answer_available(build_agent):
    agent, model, calls = build_agent(
        [[native()], [native("sbazar_search_listings", call_id="2")], final()],
        [payload(warning="Live access disabled."), payload(warning="Unsupported geography.")],
    )
    answer = agent.run("Najdi iPhone 15.")
    assert len(calls) == 2
    assert "bazos_search_listings" not in model.available_tools[1]
    assert "sbazar_search_listings" in model.available_tools[1]
    assert model.available_tools[-1] == ["final_answer"]
    assert "Live access disabled" in answer and "Unsupported geography" in answer
    system_prompt = str(model.requests[0][0])
    assert "image_generator" not in system_prompt
    assert "Action:" not in system_prompt


def test_turnov_regression_keeps_results_and_filters_despite_prose_and_retry_attempts(build_agent):
    args = {"query": "iPhone 17", "max_price": 17000, "location": "51101", "radius_km": 30}
    agent, model, calls = build_agent(
        [
            [native("lookup_postcode", {"place": "Turnov"})],
            [native(args=args)],
            "Zkusím Sbazar se stejnými parametry.",
            [native("sbazar_search_listings", args, "2")],
            [native("sbazar_search_listings", {"query": "iPhone 17", "max_price": 17000}, "3")],
            final(),
        ],
        [payload(warning="Live Bazos access is disabled."), payload(warning="Radius unsupported.")],
    )
    agent.postcode_lookup.ddgs = Mock()
    agent.postcode_lookup.ddgs.text.return_value = [
        {
            "title": "PSČ Turnov",
            "body": "PSČ 511 01",
            "href": "https://postcodes.test/turnov",
        }
    ]
    answer = agent.run("Najdi mi iPhone 17 v okolí 30km od Turnova. Cena do 17 000.")
    assert len(calls) == 2
    assert all(arguments["location"] == "51101" for _, arguments in calls)
    assert agent.last_results["search"]["radius_km"] == 30
    assert agent.last_results["search"]["max_price"] == 17000
    assert agent.last_results["searched_sources"] == ["Bazoš", "Sbazar"]
    assert model.available_tools[-1] == ["final_answer"]
    assert "disabled" in answer and "unsupported" in answer


@pytest.mark.parametrize(
    "changed",
    [
        {"location": None, "radius_km": None},
        {"radius_km": 1000},
        {"max_price": None},
        {"query": "PS5"},
    ],
)
def test_later_steps_cannot_change_filters_after_source_failure(build_agent, changed):
    args = {"query": "iPhone 15", "max_price": 17000, "location": "51101", "radius_km": 30}
    agent, _, calls = build_agent(
        [[native(args=args)], [native("sbazar_search_listings", args | changed, "2")], final()],
        [payload(warning="Access disabled.")],
    )
    agent.run("Najdi iPhone 15 do 17000 Kč v okolí PSČ 51101 do 30 km.")
    assert len(calls) == 1
    assert agent.last_results["search"]["location"] == "51101"
    assert agent.last_results["search"]["max_price"] == 17000


def test_higher_default_budget_allows_recovery_after_eight_steps(build_agent):
    agent, model, _ = build_agent([*["Zkusím to."] * 9, final("Co hledáš?")], [])
    assert agent.max_steps == 20
    assert agent.run("Najdi něco.") == "Co hledáš?"
    assert len(model.requests) == 10


def test_explicit_source_blocks_model_fallback_after_a_marketplace_failure(build_agent):
    agent, model, calls = build_agent(
        [[native()], [native("sbazar_search_listings", call_id="2")], final()],
        [payload(warning="Access disabled.")],
    )
    agent.run("Najdi iPhone 15, pouze Bazoš.")
    assert [name for name, _ in calls] == ["bazos_search_listings"]
    assert "sbazar_search_listings" not in agent.tools
    assert "sbazar_search_listings" in str(model.requests[-1])
    assert agent.last_results["searched_sources"] == ["Bazoš"]


def test_source_selection_persists_and_can_return_to_both_marketplaces():
    assert requested_sources(["Najdi iPhone."]) == {"bazos", "sbazar"}
    assert requested_sources(["Jen na Bazoši.", "Do 12000 Kč."]) == {"bazos"}
    assert requested_sources(["Only Sbazar."]) == {"sbazar"}
    assert requested_sources(["Jen Bazoš.", "Prohledej oba bazary."]) == {"bazos", "sbazar"}


def test_partial_failure_and_radius_warning_override_model_prose(build_agent):
    args = {"query": "iPhone 15", "location": "46001", "radius_km": 30}
    agent, _, _ = build_agent(
        [
            [native(args=args), native("sbazar_search_listings", args, "2")],
            final("Misleading success"),
        ],
        [
            payload(listing(), warning="Exact distances cannot be verified."),
            {"error": "Tool timed out."},
        ],
    )
    answer = agent.run("Najdi iPhone v okolí PSČ 46001 do 30 km.")
    assert "Misleading success" not in answer
    assert "Exact distances cannot be verified" in answer and "timed out" in answer
    assert agent.last_results["count"] == 1
    assert agent.last_results["geography_verified"] is False


def test_invalid_arguments_can_be_corrected_without_executing_them(build_agent):
    agent, _, calls = build_agent(
        [[native(args={"query": "iPhone 15", "limit": 0})], [native(call_id="2")], final()],
        [payload()],
    )
    agent.run("Najdi iPhone.")
    assert len(calls) == 1


def test_inferred_postcode_never_executes_mcp(build_agent):
    agent, _, calls = build_agent(
        [[native(args={"query": "iPhone 15", "location": "46001"})], final("Jaké PSČ mám použít?")],
        [],
    )
    answer = agent.run("Najdi iPhone v Liberci.")
    assert "PSČ" in answer
    assert not calls


def test_native_online_lookup_enables_mcp_search_and_retains_evidence_for_followup(build_agent):
    args = {"query": "iPhone 15", "max_price": 12000, "location": "46001", "radius_km": 30}
    agent, model, calls = build_agent(
        [
            [native("lookup_postcode", {"place": "Liberec 1"})],
            [native(args=args), native("sbazar_search_listings", args, "2")],
            final(),
            [native(args=args)],
            final(),
        ],
        [payload(), payload(), payload()],
    )
    agent.postcode_lookup.ddgs = Mock()
    agent.postcode_lookup.ddgs.text.return_value = [
        {
            "title": "PSČ 460 01, Liberec 1",
            "href": "https://www.psc.cz/46001/",
            "body": "Poštovní směrovací číslo: 460 01.",
        }
    ]
    answer = agent.run("Najdi iPhone 15 do 12000 Kč v okolí Liberce 1 do 30 km.")
    assert len(calls) == 2
    assert agent.last_results["search"]["location"] == "46001"
    assert "https://www.psc.cz/46001/" in answer
    assert "46001" in str(model.requests[1])
    agent.run("A teď jen Bazoš.", reset=False)
    assert len(calls) == 3
    assert "lookup_postcode" in model.available_tools[3]
    agent.postcode_lookup.ddgs.text.assert_called_once()
    agent.clear()
    assert not agent.postcode_lookup.resolved


def test_ambiguous_online_lookup_requires_clarification_before_mcp(build_agent):
    agent, _, calls = build_agent(
        [
            [native("lookup_postcode", {"place": "Liberec"})],
            [native(args={"query": "iPhone", "location": "46001"})],
            final("Kterou část Liberce mám použít?"),
        ],
        [],
    )
    agent.postcode_lookup.ddgs = Mock()
    agent.postcode_lookup.ddgs.text.return_value = [
        {"title": "PSČ Liberec", "href": "https://www.psc.cz/", "body": "PSČ 46001, 46006"}
    ]
    assert "Kterou část" in agent.run("Najdi iPhone v Liberci.")
    assert not calls


def test_inconsistent_batch_filters_are_rejected(build_agent):
    agent, _, calls = build_agent(
        [[native(), native("sbazar_search_listings", {"query": "PS5"}, "2")], final()], [payload()]
    )
    agent.run("Search.")
    assert len(calls) == 1


def test_iteration_and_call_limits(build_agent):
    agent, _, calls = build_agent(
        [[native()], [native(call_id="2")]], [payload(), payload()], agent_max_iterations=2
    )
    with pytest.raises(AgentError, match="Maximum agent iterations"):
        agent.run("Search.")
    assert len(calls) == 1  # Repeating a completed source never executes MCP again.
    agent, _, calls = build_agent(
        [[native(), native("sbazar_search_listings", call_id="2")]], [], agent_max_tool_calls=1
    )
    with pytest.raises(AgentError, match="Maximum tool calls"):
        agent.run("Search.")
    assert not calls


def test_history_retains_filters_and_clear_resets_memory(build_agent):
    args = {"query": "iPhone 15", "max_price": 12000, "location": "46001", "radius_km": 30}
    agent, model, _ = build_agent(
        [[native()], final(), [native(args=args)], final()], [payload(listing()), payload()]
    )
    agent.run("Najdi iPhone 15 do 12000 Kč, jen Bazoš.")
    agent.run("A teď PSČ 46001 do 30 km.", reset=False)
    assert "12000" in str(model.requests[2])
    assert agent.last_results["search"]["max_price"] == 12000
    agent.clear()
    assert not agent.memory.steps


def test_history_budget_evicts_whole_old_turns(build_agent):
    agent, _, _ = build_agent(
        [final("First"), final("Second"), final("Third")], [], agent_history_turns=1
    )
    agent.run("one")
    agent.run("two", reset=False)
    assert [step.task for step in agent.memory.steps if isinstance(step, TaskStep)] == ["two"]


def test_final_answer_excludes_only_retrieved_urls(build_agent):
    accessory = listing(100, "accessory", title="Case")
    agent, _, _ = build_agent(
        [[native()], final(exclude=["accessory"])], [payload(accessory, listing())]
    )
    agent.run("Nechci pouzdra.")
    assert agent.last_results["count"] == 1
    assert agent.last_results["listings"][0]["title"] == "iPhone 15"


def test_clarification_uses_native_final_tool_without_mcp(build_agent):
    agent, _, calls = build_agent([final("Co hledáš?")], [])
    assert agent.run("Najdi něco.") == "Co hledáš?"
    assert not calls


def test_postcodes_are_grounded_only_in_user_tasks():
    assert supplied_postcodes(["iPhone do 12000 Kč v Liberci."]) == set()
    assert supplied_postcodes(["PSČ 110 00 do 50 km", "46001"]) == {"11000", "46001"}
