"""Bazos search using the public form, ordinary HTTP, and a small HTML parser."""

import os
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from marketplace_agent.domain.models import Listing, SearchRequest
from marketplace_agent.providers.common import (
    USER_AGENT,
    SourceUnavailable,
    search_result,
)

BASE_URL = "https://www.bazos.cz"


def build_search_url(request: SearchRequest, *, offset: int = 0) -> str:
    """Use the global form, not a guessed product/category path."""
    params = {"hledat": request.query, "rubriky": "www", "kitx": "ano"}
    if offset:
        params["crz"] = str(offset)
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
    listings, pages, offset, has_more, warning = [], 0, 0, False, None
    for _ in range(request.max_pages):
        try:
            response = await client.get(
                build_search_url(request, offset=offset), follow_redirects=False
            )
            response.raise_for_status()
            if "text/html" not in response.headers.get("content-type", ""):
                raise SourceUnavailable("Bazos did not return an HTML search page.")
            batch = parse_listings(response.text, str(response.url))
            soup = BeautifulSoup(response.text, "html.parser")
            query = soup.select_one('input[name="hledat"]')
            if batch and (query is None or str(query.get("value", "")).strip() != request.query):
                raise SourceUnavailable("Bazos did not confirm the requested text search.")
            if request.location is not None:
                postcode = soup.select_one('input[name="hlokalita"]')
                radius = soup.select_one('input[name="humkreis"]')
                expected = str(request.radius_km if request.radius_km is not None else 25)
                if (
                    postcode is None
                    or str(postcode.get("value", "")).replace(" ", "") != request.location
                    or radius is None
                    or radius.get("value") != expected
                ):
                    raise SourceUnavailable(
                        "Bazos did not confirm the requested postcode/radius filter."
                    )
                warning = (
                    f"Requested the source's {expected} km postcode filter. "
                    "Exact distances cannot be verified from listing locations."
                )
        except (SourceUnavailable, httpx.HTTPError) as exc:
            if not pages:
                raise
            warning = (
                f"{warning or ''} Further Bazos page failed "
                f"({type(exc).__name__}); partial results."
            )
            break
        listings.extend(batch)
        pages += 1
        offsets = []
        for link in soup.find_all("a", href=True):
            target = urlsplit(urljoin(str(response.url), link["href"]))
            params = parse_qs(target.query)
            value = params.get("crz", [""])[0]
            if (
                target.netloc == urlsplit(BASE_URL).netloc
                and target.path == "/search.php"
                and params.get("hledat") == [request.query]
                and value.isdigit()
                and int(value) > offset
            ):
                offsets.append(int(value))
        has_more = bool(offsets) and bool(batch)
        if not has_more:
            break
        offset = min(offsets)
    return search_result(request, listings, pages, has_more, warning)


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
