"""Sbazar JSON search adapter; live access requires permission and an allowing policy."""

import os
import re
from urllib.parse import urlencode

import httpx

from marketplace_agent.domain.models import Listing, SearchRequest
from marketplace_agent.providers.common import (
    USER_AGENT,
    SourceUnavailable,
    filter_and_sort,
    robots_allows,
)

BASE_URL = "https://www.sbazar.cz"
# Reference endpoint, not a documented public API; live verification is restricted.
SEARCH_PATH = "/api/v1/items/search"


def build_search_url(request: SearchRequest) -> str:
    """Use the reference's phrase/price parameters; sort one bounded page locally."""
    params = {"phrase": request.query, "limit": "60"}
    if request.min_price is not None:
        params["price_from"] = str(request.min_price)
    if request.max_price is not None:
        params["price_to"] = str(request.max_price)
    return f"{BASE_URL}{SEARCH_PATH}?{urlencode(params)}"


def _text(value: object) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def parse_locality(value: object) -> str | None:
    """Keep only supplied locality labels, with repeated components removed."""
    if not isinstance(value, dict):
        return None
    parts = [_text(value.get(key)) for key in ("quarter", "municipality", "district")]
    return ", ".join(dict.fromkeys(part for part in parts if part)) or None


def parse_listings(payload: object) -> list[Listing]:
    """Normalize search summaries; missing values are never inferred from descriptions."""
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("results"), list)
        or payload.get("error")
        or payload.get("errors")
    ):
        raise SourceUnavailable("Sbazar returned an unrecognized JSON search response.")
    listings = []
    seen = set()
    for item in payload["results"]:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        title = _text(item.get("name"))
        slug = _text(item.get("seo_name"))
        if (
            type(item_id) is not int
            or item_id <= 0
            or not title
            or not slug
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug)
            or item_id in seen
        ):
            continue
        # The reference's search and smoke client differ on whether seo_name includes id.
        if not slug.startswith(f"{item_id}-"):
            slug = f"{item_id}-{slug}"
        price = item.get("price")
        if (
            type(price) is not int
            or price < 0
            or item.get("price_by_agreement", False) is not False
        ):
            price = None
        listings.append(
            Listing(
                title=title,
                price=price,
                location=parse_locality(item.get("locality")),
                url=f"{BASE_URL}/inzerat/{slug}",
                description=_text(item.get("description")),
            )
        )
        seen.add(item_id)
    if payload["results"] and not listings:
        raise SourceUnavailable("Sbazar returned no recognizable listing summaries.")
    return listings


async def _search(request: SearchRequest, client: httpx.AsyncClient) -> dict:
    url = build_search_url(request)
    robots = await client.get(f"{BASE_URL}/robots.txt", follow_redirects=False)
    robots.raise_for_status()
    if not robots_allows(robots.text, url, source="Sbazar"):
        raise SourceUnavailable(
            "Sbazar robots.txt disallows automated search; no search was fetched."
        )
    response = await client.get(url, follow_redirects=False)
    response.raise_for_status()
    if "application/json" not in response.headers.get("content-type", "").lower():
        raise SourceUnavailable("Sbazar did not return a JSON search response.")
    try:
        payload = response.json()
    except ValueError as error:
        raise SourceUnavailable("Sbazar returned invalid JSON.") from error
    selected = filter_and_sort(parse_listings(payload), request)
    return {
        "query": request.query,
        "count": len(selected),
        "listings": [listing.model_dump() for listing in selected],
    }


async def search_listings(request: SearchRequest, client: httpx.AsyncClient | None = None) -> dict:
    """Fetch one JSON result page; never silently ignore geographic restrictions."""
    empty = {"query": request.query, "count": 0, "listings": []}
    if request.location is not None:
        return empty | {
            "warning": (
                "Sbazar postcode/radius filtering is unsupported by this adapter: no reliable "
                "native parameters or coordinates were verified. No search was fetched and no "
                "unverified geographic matches are returned."
            )
        }
    if os.environ.get("SBAZAR_ACCESS_PERMITTED") != "true":
        return empty | {
            "warning": (
                "Live Sbazar access is disabled. Obtain Sbazar operator permission before setting "
                "SBAZAR_ACCESS_PERMITTED=true. Robots restrictions will still be enforced."
            )
        }
    try:
        if client is not None:
            return await _search(request, client)
        async with httpx.AsyncClient(
            timeout=15, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        ) as owned_client:
            return await _search(request, owned_client)
    except SourceUnavailable as error:
        warning = str(error)
    except httpx.HTTPStatusError as error:
        warning = (
            f"Sbazar is unavailable (HTTP {error.response.status_code}); no listings returned."
        )
    except httpx.RequestError:
        warning = "Sbazar request failed or timed out; no listings returned."
    return empty | {"warning": warning}
