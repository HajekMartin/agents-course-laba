"""Bounded native pagination, including accessory-only first pages and partial failures."""

import asyncio

import httpx
import pytest

from marketplace_agent.domain.models import SearchRequest
from marketplace_agent.providers import bazos, sbazar


def bazos_page(*items, next_offset=None):
    form = '<form><input name="hledat" value="iPhone 17"></form>'
    rows = "".join(
        '<div class="inzeraty"><h2 class="nadpis">'
        f'<a href="https://mobil.bazos.cz/inzerat/{index}/test.php">{title}</a></h2>'
        f'<div class="inzeratycena">{price} Kč</div></div>'
        for index, title, price in items
    )
    link = (
        f'<a href="search.php?hledat=iPhone+17&amp;crz={next_offset}">Další</a>'
        if next_offset
        else ""
    )
    return form + rows + link


@pytest.mark.parametrize("max_pages, expected", [(1, []), (3, [500])])
def test_bazos_scans_past_accessories_before_price_sort_and_final_limit(
    monkeypatch, max_pages, expected
):
    monkeypatch.setenv("BAZOS_ACCESS_PERMITTED", "true")
    offsets = []

    async def run():
        def respond(request):
            offset = request.url.params.get("crz", "0")
            offsets.append(offset)
            assert request.url.params["cenado"] == "17000"
            html = (
                bazos_page((1, "Kryt iPhone 17", 10), next_offset=40)
                if offset == "0"
                else bazos_page((2, "iPhone 17 poškozený displej", 500), (3, "iPhone 17", 16490))
            )
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await bazos.search_listings(
                SearchRequest(
                    query="iPhone 17",
                    max_price=17000,
                    sort_by="price_asc",
                    limit=1,
                    max_pages=max_pages,
                ),
                client,
            )

    result = asyncio.run(run())
    assert [item["price"] for item in result["listings"]] == expected
    assert result["filtered_count"] == 1
    assert result["has_more"] is (max_pages == 1)
    assert offsets == (["0"] if max_pages == 1 else ["0", "40"])


def test_later_bazos_failure_keeps_real_first_page_results(monkeypatch):
    monkeypatch.setenv("BAZOS_ACCESS_PERMITTED", "true")

    async def run():
        def respond(request):
            if request.url.params.get("crz"):
                return httpx.Response(429)
            return httpx.Response(
                200,
                text=bazos_page((1, "iPhone 17", 15000), next_offset=40),
                headers={"content-type": "text/html"},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await bazos.search_listings(SearchRequest(query="iPhone 17"), client)

    result = asyncio.run(run())
    assert result["count"] == 1 and result["pages_scanned"] == 1
    assert "partial" in result["warning"]
    assert result["has_more"] is True


@pytest.mark.parametrize("fail_second", [False, True])
def test_sbazar_native_offsets_and_partial_results(monkeypatch, fail_second):
    monkeypatch.setenv("SBAZAR_ACCESS_PERMITTED", "true")
    offsets = []

    async def run():
        def respond(request):
            offset = int(request.url.params.get("offset", "0"))
            offsets.append(offset)
            if offset and fail_second:
                return httpx.Response(503)
            rows = (
                [
                    {"id": i, "name": "Kryt iPhone 17", "price": 10, "seo_name": f"case-{i}"}
                    for i in range(1, 61)
                ]
                if offset == 0
                else [{"id": 61, "name": "Apple iPhone 17", "price": 16490, "seo_name": "phone"}]
            )
            return httpx.Response(200, json={"results": rows, "pagination": {"total": 61}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await sbazar.search_listings(
                SearchRequest(query="iPhone 17", sort_by="price_asc", limit=1), client
            )

    result = asyncio.run(run())
    assert offsets == [0, 60]
    assert result["filtered_count"] == 60
    if fail_second:
        assert result["count"] == 0 and "partial" in result["warning"]
    else:
        assert result["listings"][0]["price"] == 16490
        assert result["pages_scanned"] == 2 and result["has_more"] is False
