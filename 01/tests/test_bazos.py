"""Bazos parsing, filtering, HTTP failures and MCP without marketplace access."""

import asyncio
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from marketplace_agent.domain.models import SearchRequest
from marketplace_agent.mcp.bazos_server import mcp
from marketplace_agent.providers import bazos

HTML = (Path(__file__).parent / "fixtures" / "bazos.html").read_text(encoding="utf-8")


def search(request: SearchRequest | None = None, *, html: str = HTML) -> dict:
    async def run() -> dict:
        def respond(http_request: httpx.Request) -> httpx.Response:
            assert http_request.url.path == "/search.php"
            return httpx.Response(200, text=html, headers={"Content-Type": "text/html"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await bazos.search_listings(
                request or SearchRequest(query="test product"), client
            )

    return asyncio.run(run())


@pytest.fixture
def permitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only mocked requests are authorized in these tests."""
    monkeypatch.setenv("BAZOS_ACCESS_PERMITTED", "true")


@pytest.mark.parametrize("query", ["iPhone 15", "horské kolo", "stůl & židle", "RTX 5080"])
def test_global_search_url(query: str) -> None:
    url = urlsplit(bazos.build_search_url(SearchRequest(query=query)))
    assert (url.scheme, url.netloc, url.path) == ("https", "www.bazos.cz", "/search.php")
    assert parse_qs(url.query) == {"hledat": [query], "rubriky": ["www"], "kitx": ["ano"]}


@pytest.mark.parametrize("radius, expected", [(None, "25"), (0, "0"), (50, "50")])
def test_filter_parameters(radius: int | None, expected: str) -> None:
    request = SearchRequest(
        query="test",
        min_price=0,
        max_price=10000,
        location="460 01",
        radius_km=radius,
        sort_by="price_desc",
    )
    params = parse_qs(urlsplit(bazos.build_search_url(request)).query)
    assert params["cenaod"] == ["0"]
    assert params["cenado"] == ["10000"]
    assert params["hlokalita"] == ["46001"]
    assert params["humkreis"] == [expected]
    assert "order" not in params  # Direction is not assumed; sorting is local.


@pytest.mark.parametrize(
    "parameters",
    [
        {"query": "  "},
        {"query": "a" * 257},
        {"min_price": -1},
        {"max_price": -1},
        {"min_price": 11, "max_price": 10},
        {"min_price": True},
        {"limit": 0},
        {"limit": 51},
        {"limit": "5"},
        {"max_pages": 0},
        {"max_pages": 6},
        {"max_pages": True},
        {"radius_km": 1},
        {"location": "Liberec"},
        {"location": ""},
        {"location": "00000"},
        {"location": "46001", "radius_km": -1},
        {"location": "46001", "radius_km": 1001},
        {"sort_by": "newest"},
    ],
)
def test_invalid_parameters(parameters: dict) -> None:
    with pytest.raises(ValidationError):
        SearchRequest.model_validate({"query": "test"} | parameters)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("10 500 Kč", 10500),
        ("1\u00a0234 Kč", 1234),
        ("1\u202f234 Kč", 1234),
        ("0 Kč", 0),
        ("999Kč", 999),
        ("Dohodou", None),
        ("Nabídněte", None),
        ("", None),
        ("1 000 EUR", None),
        ("Od 500 Kč", None),
        ("100 Kč / ks", None),
        ("10 50 Kč", None),
        ("-1 Kč", None),
    ],
)
def test_price_parsing(text: str, expected: int | None) -> None:
    assert bazos.parse_price(text) == expected


def test_html_parsing() -> None:
    listings = bazos.parse_listings(HTML, "https://www.bazos.cz/search.php")
    assert len(listings) == 3
    assert listings[0].model_dump() == {
        "title": "Test phone & case",
        "price": 12500,
        "currency": "CZK",
        "location": "Liberec 460 01",
        "url": "https://mobil.bazos.cz/inzerat/100000001/test-phone.php",
        "description": "A test description. No real advertisement.",
    }
    assert listings[1].url.startswith("https://sport.bazos.cz/")
    assert listings[2].url == "https://www.bazos.cz/inzerat/100000003/test-desk.php"
    assert listings[2].price is None
    assert listings[2].location is None
    assert listings[2].description == ""
    assert (
        bazos.parse_listings(HTML.replace("Dohodou", ""), "https://www.bazos.cz/")[2].price is None
    )


@pytest.mark.parametrize(
    ("filters", "prices"),
    [
        ({}, [12500, 4000, None]),
        ({"min_price": 4000}, [12500, 4000]),
        ({"max_price": 4000}, [4000]),
        ({"min_price": 4001, "max_price": 12500}, [12500]),
        ({"min_price": 12501}, []),
        ({"sort_by": "price_asc"}, [4000, 12500, None]),
        ({"sort_by": "price_desc"}, [12500, 4000, None]),
        ({"sort_by": "price_asc", "limit": 1}, [4000]),
    ],
)
def test_price_filtering_sorting_and_limit(permitted: None, filters: dict, prices: list) -> None:
    result = search(SearchRequest(query="test product", **filters))
    assert [listing["price"] for listing in result["listings"]] == prices
    assert result["count"] == len(prices)
    assert "warning" not in result


def test_empty_and_invalid_html(permitted: None) -> None:
    assert search(html="<html><p>Nebyly nalezeny žádné inzeráty.</p></html>") == {
        "query": "test product",
        "count": 0,
        "listings": [],
        "pages_scanned": 1,
        "has_more": False,
        "scanned_count": 0,
        "filtered_count": 0,
    }
    for html in ("", "<html><p>CAPTCHA</p></html>", "not HTML", "<h2>Maintenance</h2>"):
        result = search(html=html)
        assert result["count"] == 0
        assert "unrecognized HTML" in result["warning"]


def test_unconfirmed_query_is_not_returned_as_relevant(permitted: None) -> None:
    result = search(html=HTML.replace('value="test product"', 'value="unrelated"'))
    assert result["listings"] == []
    assert "did not confirm the requested text search" in result["warning"]


def test_location_confirmation_and_distance_warning(permitted: None) -> None:
    request = SearchRequest(query="test product", location="46001")
    result = search(request)
    assert result["count"] == 3
    assert "25 km" in result["warning"]
    assert "cannot be verified" in result["warning"]
    result = search(request, html=HTML.replace('value="460 01"', 'value=""'))
    assert result["listings"] == []
    assert "did not confirm" in result["warning"]
    result = search(SearchRequest(query="test product", location="46001", radius_km=50))
    assert result["listings"] == []
    assert "did not confirm" in result["warning"]
    result = search(
        SearchRequest(query="test product", location="46001", radius_km=50),
        html=HTML.replace('value="25"', 'value="50"'),
    )
    assert result["count"] == 3
    assert "50 km" in result["warning"]


def test_access_disabled_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAZOS_ACCESS_PERMITTED", "false")

    async def run() -> dict:
        def reject(request: httpx.Request) -> httpx.Response:
            pytest.fail("Disabled access must not make HTTP requests")

        async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
            return await bazos.search_listings(SearchRequest(query="test"), client)

    result = asyncio.run(run())
    assert result["listings"] == []
    assert "disabled by configuration" in result["warning"]


def test_user_search_is_enabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BAZOS_ACCESS_PERMITTED", raising=False)
    assert search()["count"] > 0


@pytest.mark.parametrize("failure", [403, 429, 503, 302, "timeout", "json"])
def test_request_failure(permitted: None, failure: int | str) -> None:
    async def run() -> dict:
        def respond(request: httpx.Request) -> httpx.Response:
            if failure == "timeout":
                raise httpx.ReadTimeout("test timeout", request=request)
            if failure == "json":
                return httpx.Response(200, json={"unavailable": True})
            return httpx.Response(failure, headers={"Location": "https://example.com/"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await bazos.search_listings(SearchRequest(query="test"), client)

    result = asyncio.run(run())
    assert result["listings"] == []
    assert result["warning"]


def test_mcp_tool_registration_invocation_and_validation(
    monkeypatch: pytest.MonkeyPatch,
    permitted: None,
) -> None:
    original = bazos.search_listings

    async def mocked_search(request: SearchRequest) -> dict:
        def respond(http_request: httpx.Request) -> httpx.Response:
            assert http_request.url.params["cenaod"] == "4000"
            return httpx.Response(200, text=HTML, headers={"Content-Type": "text/html"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await original(request, client)

    monkeypatch.setattr(bazos, "search_listings", mocked_search)

    async def run() -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            assert [tool.name for tool in tools] == ["search_listings"]
            assert set(tools[0].inputSchema["properties"]) == {
                "query",
                "min_price",
                "max_price",
                "location",
                "radius_km",
                "sort_by",
                "limit",
                "max_pages",
            }
            result = await client.call_tool(
                "search_listings",
                {
                    "query": "test product",
                    "min_price": 4000,
                    "sort_by": "price_asc",
                    "limit": 1,
                },
            )
            assert result.data["count"] == 1
            assert result.data["listings"][0]["price"] == 4000
            for params in (
                {"query": " "},
                {"query": "test", "radius_km": 1},
                {"query": "test", "min_price": 10, "max_price": 1},
                {"query": "test", "limit": "5"},
            ):
                with pytest.raises(ToolError):
                    await client.call_tool("search_listings", params)

    asyncio.run(run())


def test_streamable_http_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAZOS_ACCESS_PERMITTED", "false")

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
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                },
            )
            assert response.status_code == 200
            assert response.json()["result"]["serverInfo"]["name"] == "Bazos MCP"
            client.headers["MCP-Protocol-Version"] = response.json()["result"]["protocolVersion"]
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                },
            )
            assert [tool["name"] for tool in response.json()["result"]["tools"]] == [
                "search_listings"
            ]
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "search_listings", "arguments": {"query": "test"}},
                },
            )
            assert response.status_code == 200
            result = response.json()["result"]["structuredContent"]
            assert result["listings"] == []
            assert "disabled by configuration" in result["warning"]

    asyncio.run(run())


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("BAZOS_LIVE_SMOKE") != "true",
    reason="Set BAZOS_LIVE_SMOKE=true for live requests",
)
def test_optional_live_smoke() -> None:
    result = asyncio.run(bazos.search_listings(SearchRequest(query="kolo", limit=1)))
    assert result["count"] == len(result["listings"]) == 1, result
    assert 1 <= result["pages_scanned"] <= 3
    assert result["listings"][0]["url"].startswith("https://")
    if result["has_more"]:
        assert "further source results were not fetched" in result["warning"]
