"""Bazos search using the public form, ordinary HTTP, and a small HTML parser."""

import os
import re
from urllib.parse import urlencode, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from marketplace_agent.domain.models import Listing, SearchRequest
from marketplace_agent.providers.common import (
    USER_AGENT,
    SourceUnavailable,
    filter_and_sort,
)

BASE_URL = "https://www.bazos.cz"


def build_search_url(request: SearchRequest) -> str:
    """Use the global form, not a guessed product/category path."""
    params = {"hledat": request.query, "rubriky": "www", "kitx": "ano"}
    if request.min_price is not None:
        params["cenaod"] = str(request.min_price)
    if request.max_price is not None:
        params["cenado"] = str(request.max_price)
    if request.location is not None:
        params["hlokalita"] = request.location
        params["humkreis"] = str(request.radius_km if request.radius_km is not None else 25)
    # The current page exposes order=1 for price, but its direction/toggle behavior
    # cannot be verified without restricted searches. Sort the fetched page locally.
    return f"{BASE_URL}/search.php?{urlencode(params)}"


def parse_price(value: str) -> int | None:
    """Accept an explicit whole CZK amount, never guess a negotiated/unit price."""
    value = " ".join(value.split())
    match = re.fullmatch(r"([0-9]+|[0-9]{1,3}(?: [0-9]{3})+)\s*Kč", value, re.IGNORECASE)
    return int(match[1].replace(" ", "")) if match else None


def parse_listings(html: str, page_url: str) -> list[Listing]:
    """Extract listing summaries only; never fetch seller or detail pages."""
    soup = BeautifulSoup(html, "html.parser")
    listings = []
    seen = set()
    rows = soup.select(".inzeraty")
    for row in rows:
        link = row.select_one("h2.nadpis a[href]")
        if link is None or not link.get_text(strip=True):
            continue
        url = urljoin(page_url, str(link["href"]))
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or not (parts.hostname or "").endswith(".bazos.cz")
            or not re.fullmatch(r"/inzerat/[0-9]+/[^/]+\.php", parts.path)
            or url in seen
        ):
            continue
        price = row.select_one(".inzeratycena")
        location = row.select_one(".inzeratylok")
        description = row.select_one(".popis")
        listings.append(
            Listing(
                title=link.get_text(" ", strip=True),
                price=parse_price(price.get_text(" ", strip=True)) if price else None,
                location=(location.get_text(" ", strip=True) or None) if location else None,
                url=url,
                description=description.get_text(" ", strip=True) if description else "",
            )
        )
        seen.add(url)
    if not listings and not re.search(
        r"(?:žádné inzeráty|inzeráty nenalezeny|nic nenalezeno|inzerátů:\s*0\b|0 inzerátů)",
        soup.get_text(" ", strip=True),
        re.IGNORECASE,
    ):
        raise SourceUnavailable("Bazos returned unrecognized HTML or an access challenge.")
    return listings


async def _search(request: SearchRequest, client: httpx.AsyncClient) -> dict:
    url = build_search_url(request)
    response = await client.get(url, follow_redirects=False)
    response.raise_for_status()
    if "text/html" not in response.headers.get("content-type", ""):
        raise SourceUnavailable("Bazos did not return an HTML search page.")
    listings = parse_listings(response.text, str(response.url))
    soup = BeautifulSoup(response.text, "html.parser")
    query = soup.select_one('input[name="hledat"]')
    if listings and (query is None or str(query.get("value", "")).strip() != request.query):
        raise SourceUnavailable("Bazos did not confirm the requested text search.")
    result = {"query": request.query, "count": 0, "listings": []}
    if request.location is not None:
        postcode = soup.select_one('input[name="hlokalita"]')
        radius = soup.select_one('input[name="humkreis"]')
        expected_radius = str(request.radius_km if request.radius_km is not None else 25)
        if (
            postcode is None
            or str(postcode.get("value", "")).replace(" ", "") != request.location
            or radius is None
            or radius.get("value") != expected_radius
        ):
            raise SourceUnavailable("Bazos did not confirm the requested postcode/radius filter.")
        result["warning"] = (
            f"Requested the source's {expected_radius} km postcode filter. "
            "Exact distances cannot be verified from listing locations."
        )
    selected = filter_and_sort(listings, request)
    result.update(count=len(selected), listings=[listing.model_dump() for listing in selected])
    return result


async def search_listings(request: SearchRequest, client: httpx.AsyncClient | None = None) -> dict:
    """Fetch one public result page for the user's request; do not bypass access errors."""
    empty = {"query": request.query, "count": 0, "listings": []}
    if os.environ.get("BAZOS_ACCESS_PERMITTED", "true") != "true":
        return empty | {
            "warning": (
                "Live Bazos requests are disabled by configuration (BAZOS_ACCESS_PERMITTED=false)."
            )
        }
    try:
        if client is not None:
            return await _search(request, client)
        async with httpx.AsyncClient(
            timeout=15, headers={"User-Agent": USER_AGENT}
        ) as owned_client:
            return await _search(request, owned_client)
    except SourceUnavailable as error:
        warning = str(error)
    except httpx.HTTPStatusError as error:
        warning = f"Bazos is unavailable (HTTP {error.response.status_code}); no listings returned."
    except httpx.RequestError:
        warning = "Bazos request failed or timed out; no listings returned."
    return empty | {"warning": warning}
