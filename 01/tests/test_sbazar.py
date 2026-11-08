"""Sbazar JSON integration and MCP contract, without live marketplace requests."""

import asyncio
import copy
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from marketplace_agent.domain.models import SearchRequest
from marketplace_agent.mcp.bazos_server import mcp as bazos_mcp
from marketplace_agent.mcp.sbazar_server import mcp
from marketplace_agent.providers import sbazar

PAYLOAD = json.loads((Path(__file__).parent / "fixtures" / "sbazar.json").read_text())


@pytest.fixture
def permitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Authorize only the mocked requests in tests that use this fixture."""
    monkeypatch.setenv("SBAZAR_ACCESS_PERMITTED", "true")


def search(request: SearchRequest | None = None, *, payload: object = PAYLOAD) -> dict:
    async def run() -> dict:
        def respond(http_request: httpx.Request) -> httpx.Response:
            assert http_request.url.path == sbazar.SEARCH_PATH
            return httpx.Response(200, json=payload)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await sbazar.search_listings(request or SearchRequest(query="test"), client)

    return asyncio.run(run())


@pytest.mark.parametrize("query", ["iPhone 15", "horské kolo", "stůl & židle", "100% + sleva"])
@pytest.mark.parametrize(
    "prices", [{}, {"min_price": 0}, {"max_price": 10000}, {"min_price": 4000, "max_price": 12500}]
)
def test_search_request(query: str, prices: dict) -> None:
    request = SearchRequest(query=query, limit=1, sort_by="price_desc", **prices)
    url = urlsplit(sbazar.build_search_url(request))
    assert (url.scheme, url.netloc, url.path) == ("https", "www.sbazar.cz", sbazar.SEARCH_PATH)
    expected = {"phrase": [query], "limit": ["60"]}
    if "min_price" in prices:
        expected["price_from"] = [str(prices["min_price"])]
    if "max_price" in prices:
        expected["price_to"] = [str(prices["max_price"])]
    assert parse_qs(url.query) == expected


def test_parse_listing_fields() -> None:
    listings = sbazar.parse_listings(PAYLOAD)
    assert len(listings) == 5
    assert listings[0].model_dump() == {
        "title": "Test phone & case",
        "price": 12500,
        "currency": "CZK",
        "location": "Liberec",
        "url": "https://www.sbazar.cz/inzerat/100000001-test-phone",
        "description": "Invented test listing, not a real advertisement.",
    }
    assert listings[1].url == "https://www.sbazar.cz/inzerat/100000002-test-bike"
    assert listings[1].location == "Turnov, Semily"
    assert listings[2].price is None
    assert listings[2].location is None
    assert listings[3].price == 0
    assert listings[3].description is None
    assert listings[4].price is None
    assert listings[4].description is None


@pytest.mark.parametrize("price", [None, "10500", "Dohodou", True, -1, 1.5, {}, []])
def test_invalid_or_missing_price_is_unknown(price: object) -> None:
    payload = copy.deepcopy(PAYLOAD)
    payload["results"][0]["price"] = price
    assert sbazar.parse_listings(payload)[0].price is None


def test_agreed_price_is_unknown_even_with_a_numeric_amount() -> None:
    payload = copy.deepcopy(PAYLOAD)
    payload["results"][0].update(price=12500, price_by_agreement=True)
    assert sbazar.parse_listings(payload)[0].price is None


@pytest.mark.parametrize("value", [None, "Liberec", [], {}, {"municipality": 123}])
def test_invalid_or_missing_locality(value: object) -> None:
    assert sbazar.parse_locality(value) is None


def test_invalid_optional_fields_and_duplicate_or_unsafe_listings() -> None:
    payload = copy.deepcopy(PAYLOAD)
    payload["results"][0].update(description={"text": "invalid"}, locality=["invalid"])
    for fields in (
        {"id": True},
        {"name": " "},
        {"seo_name": "//evil.example/path"},
        {"seo_name": "../test"},
        {"seo_name": "test?next=evil"},
        {"seo_name": None},
    ):
        payload["results"].append(PAYLOAD["results"][0] | fields)
    payload["results"].extend([None, "invalid", PAYLOAD["results"][0]])
    listings = sbazar.parse_listings(payload)
    assert len(listings) == 5
    assert listings[0].description is None
    assert listings[0].location is None


@pytest.mark.parametrize(
    ("filters", "prices"),
    [
        ({}, [12500, 4000, None, 0, None]),
        ({"min_price": 0}, [12500, 4000, 0]),
        ({"max_price": 0}, [0]),
        ({"min_price": 4000}, [12500, 4000]),
        ({"max_price": 4000}, [4000, 0]),
        ({"min_price": 4000, "max_price": 12500}, [12500, 4000]),
        ({"min_price": 4000, "max_price": 4000}, [4000]),
        ({"min_price": 12501}, []),
        ({"sort_by": "price_asc"}, [0, 4000, 12500, None, None]),
        ({"sort_by": "price_desc"}, [12500, 4000, 0, None, None]),
        ({"sort_by": "price_asc", "limit": 1}, [0]),
        ({"sort_by": "price_desc", "limit": 1}, [12500]),
    ],
)
def test_price_filters_sort_and_limit(permitted: None, filters: dict, prices: list) -> None:
    result = search(SearchRequest(query="test", **filters))
    assert result["query"] == "test"
    assert result["count"] == len(prices)
    assert [listing["price"] for listing in result["listings"]] == prices
    assert "warning" not in result


def test_sort_ties_keep_source_order(permitted: None) -> None:
    payload = copy.deepcopy(PAYLOAD)
    for item in payload["results"]:
        item.update(price=1000, price_by_agreement=False)
    for order in ("relevance", "price_asc", "price_desc"):
        result = search(SearchRequest(query="test", sort_by=order), payload=payload)
        assert [listing["title"] for listing in result["listings"]] == [
            item["name"] for item in payload["results"]
        ]


def test_empty_results(permitted: None) -> None:
    assert search(payload={"results": []}) == {
        "query": "test",
        "count": 0,
        "listings": [],
        "pages_scanned": 1,
        "has_more": False,
        "scanned_count": 0,
        "filtered_count": 0,
    }


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"results": None},
        {"results": {}},
        {"results": [None, {}]},
        {"results": [], "error": "invalid phrase"},
    ],
)
def test_invalid_payload_is_not_a_successful_empty_search(permitted: None, payload: object) -> None:
    result = search(payload=payload)
    assert result["listings"] == []
    assert result["warning"]


def test_access_disabled_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SBAZAR_ACCESS_PERMITTED", "false")

    async def run() -> dict:
        def reject(request: httpx.Request) -> httpx.Response:
            pytest.fail("Disabled access must not make HTTP requests")

        async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
            return await sbazar.search_listings(SearchRequest(query="test"), client)

    assert "disabled by configuration" in asyncio.run(run())["warning"]


def test_user_search_is_enabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SBAZAR_ACCESS_PERMITTED", raising=False)
    assert search()["count"] > 0


@pytest.mark.parametrize("radius, expected", [(None, 25), (0, 0), (30, 30), (1000, 1000)])
def test_native_geography_resolves_postcode_and_preserves_radius(permitted, radius, expected):
    calls = []

    async def run():
        def respond(request):
            calls.append(request.url.path)
            assert request.url.path != "/robots.txt"
            if request.url.path == sbazar.LOCALITY_PATH:
                assert dict(request.url.params) == {"query": "51101", "include_zip": "1"}
                return httpx.Response(
                    200,
                    json={
                        "results": [
                            {
                                "entity_id": 2751,
                                "entity_type": "municipality",
                                "suggest_first_row": "Turnov",
                            },
                            {
                                "entity_id": 14581,
                                "entity_type": "ward",
                                "suggest_first_row": "Turnov",
                            },
                        ]
                    },
                )
            assert request.url.path == sbazar.SEARCH_PATH
            assert request.url.params["locality"] == "municipality,2751"
            assert request.url.params["radius_precision"] == str(expected)
            assert request.url.params["price_to"] == "17000"
            return httpx.Response(200, json=PAYLOAD)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await sbazar.search_listings(
                SearchRequest(
                    query="test",
                    max_price=17000,
                    location="51101",
                    radius_km=radius,
                ),
                client,
            )

    result = asyncio.run(run())
    assert result["count"] > 0
    assert "Turnov" in result["warning"] and "unverified" in result["warning"]
    assert calls == [sbazar.LOCALITY_PATH, sbazar.SEARCH_PATH]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"results": []},
        {"results": None},
        {
            "results": [
                {"entity_type": "municipality", "entity_id": "2751", "suggest_first_row": "Turnov"},
            ]
        },
    ],
)
def test_unresolved_postcode_never_falls_back_to_unfiltered_search(permitted, payload):
    async def run():
        def respond(request):
            assert request.url.path == sbazar.LOCALITY_PATH
            return httpx.Response(200, json=payload)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await sbazar.search_listings(
                SearchRequest(query="test", location="51101"), client
            )

    result = asyncio.run(run())
    assert result["listings"] == []
    assert "could not resolve the postcode" in result["warning"]


@pytest.mark.parametrize("status", [403, 429, 503])
def test_geographic_lookup_http_failure_is_reported_without_search(permitted, status):
    async def run():
        def respond(request):
            assert request.url.path == sbazar.LOCALITY_PATH
            return httpx.Response(status)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await sbazar.search_listings(
                SearchRequest(query="test", location="51101"), client
            )

    result = asyncio.run(run())
    assert result["listings"] == []
    assert str(status) in result["warning"]


@pytest.mark.parametrize("failure", [403, 429, 503, 302, "timeout", "connect"])
def test_http_failures(permitted: None, failure: int | str) -> None:
    async def run() -> dict:
        def respond(request: httpx.Request) -> httpx.Response:
            if failure == "timeout":
                raise httpx.ReadTimeout("test timeout", request=request)
            if failure == "connect":
                raise httpx.ConnectError("test failure", request=request)
            return httpx.Response(failure, headers={"Location": "https://example.com/"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await sbazar.search_listings(SearchRequest(query="test"), client)

    result = asyncio.run(run())
    assert result["listings"] == []
    assert result["warning"]


@pytest.mark.parametrize(
    "content_type, content",
    [("text/html", "<html>CAPTCHA</html>"), ("application/json", "invalid json")],
)
def test_invalid_http_response(permitted: None, content_type: str, content: str) -> None:
    async def run() -> dict:
        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=content, headers={"Content-Type": content_type})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await sbazar.search_listings(SearchRequest(query="test"), client)

    result = asyncio.run(run())
    assert result["listings"] == []
    assert "JSON" in result["warning"]


def test_mcp_contract_and_invocation(monkeypatch: pytest.MonkeyPatch, permitted: None) -> None:
    original = sbazar.search_listings

    async def mocked_search(request: SearchRequest) -> dict:
        def respond(http_request: httpx.Request) -> httpx.Response:
            assert http_request.url.params["phrase"] == "test"
            assert http_request.url.params["price_from"] == "4000"
            return httpx.Response(200, json=PAYLOAD)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await original(request, client)

    monkeypatch.setattr(sbazar, "search_listings", mocked_search)

    async def run() -> None:
        async with Client(mcp) as client, Client(bazos_mcp) as other:
            tools = await client.list_tools()
            bazos_tools = await other.list_tools()
            assert [tool.name for tool in tools] == ["search_listings"]
            assert tools[0].inputSchema == bazos_tools[0].inputSchema
            assert tools[0].outputSchema == bazos_tools[0].outputSchema
            result = await client.call_tool(
                "search_listings",
                {
                    "query": " test ",
                    "min_price": 4000,
                    "max_price": 12500,
                    "sort_by": "price_asc",
                    "limit": 1,
                },
            )
            assert result.data["query"] == "test"
            assert result.data["count"] == 1
            assert result.data["listings"][0]["price"] == 4000
            for parameters in (
                {"query": " "},
                {"query": "a" * 257},
                {"min_price": -1},
                {"min_price": True},
                {"min_price": 10, "max_price": 1},
                {"location": "Liberec"},
                {"location": "00000"},
                {"radius_km": 1},
                {"location": "46001", "radius_km": 1001},
                {"limit": "5"},
                {"limit": 0},
                {"limit": 51},
                {"sort_by": "newest"},
                {"extra": "invalid"},
            ):
                with pytest.raises(ToolError):
                    await client.call_tool("search_listings", {"query": "test"} | parameters)

    asyncio.run(run())


def test_streamable_http_discovery_and_invocation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SBAZAR_ACCESS_PERMITTED", "false")

    async def run() -> None:
        app = mcp.http_app(path="/mcp", stateless_http=True, json_response=True)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app),
                base_url="http://testserver",
                headers={"Accept": "application/json, text/event-stream"},
            ) as client,
        ):

            async def rpc(identifier: int, method: str, params: dict) -> dict:
                response = await client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": identifier,
                        "method": method,
                        "params": params,
                    },
                )
                assert response.status_code == 200
                return response.json()["result"]

            init = await rpc(
                1,
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            )
            assert init["serverInfo"]["name"] == "Sbazar MCP"
            client.headers["MCP-Protocol-Version"] = init["protocolVersion"]
            tools = await rpc(2, "tools/list", {})
            assert [tool["name"] for tool in tools["tools"]] == ["search_listings"]
            result = await rpc(
                3,
                "tools/call",
                {
                    "name": "search_listings",
                    "arguments": {"query": "test"},
                },
            )
            assert not result.get("isError")
            data = result["structuredContent"]
            assert data["listings"] == []
            assert "disabled by configuration" in data["warning"]

    asyncio.run(run())


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("SBAZAR_LIVE_SMOKE") != "true",
    reason="Set SBAZAR_LIVE_SMOKE=true for live requests",
)
def test_optional_live_smoke() -> None:
    result = asyncio.run(sbazar.search_listings(SearchRequest(query="kolo", limit=1)))
    assert result["count"] == len(result["listings"]) == 1, result
    assert 1 <= result["pages_scanned"] <= 3
    assert result["listings"][0]["url"].startswith("https://")
    if result["has_more"]:
        assert "further source results were not fetched" in result["warning"]
