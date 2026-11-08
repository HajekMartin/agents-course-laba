"""User-requested Sbazar JSON search with source-native locality and radius filters."""

import os
import re
from urllib.parse import urlencode

import httpx

from marketplace_agent.domain.models import Listing, SearchRequest
from marketplace_agent.providers.common import (
    USER_AGENT,
    SourceUnavailable,
    filter_and_sort,
)

BASE_URL = "https://www.sbazar.cz"
# Public frontend endpoints, verified against its request builder; not a supported SDK.
SEARCH_PATH = "/api/v1/items/search"
LOCALITY_PATH = "/api/v2/localities/suggest"


def build_search_url(request: SearchRequest, *, locality: str | None = None) -> str:
    """Translate existing filters to the source's verified native query parameters."""
    params = {"phrase": request.query, "limit": "60"}
    if request.min_price is not None:
        params["price_from"] = str(request.min_price)
    if request.max_price is not None:
        params["price_to"] = str(request.max_price)
    if request.location is not None:
        if locality is None:
            raise SourceUnavailable("Sbazar postcode must resolve to a source locality first.")
        params["locality"] = locality
        params["radius_precision"] = str(request.radius_km if request.radius_km is not None else 25)
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
    locality = None
    warning = None
    if request.location:
        response = await client.get(
            f"{BASE_URL}{LOCALITY_PATH}",
            params={"query": request.location, "include_zip": 1},
            follow_redirects=False,
        )
        response.raise_for_status()
        try:
            candidates = response.json()["results"]
            match = next(
                item
                for item in candidates
                if item.get("entity_type") == "municipality"
                and type(item.get("entity_id")) is int
                and item["entity_id"] > 0
                and isinstance(item.get("suggest_first_row"), str)
                and item["suggest_first_row"].strip()
            )
        except (ValueError, KeyError, TypeError, AttributeError, StopIteration) as exc:
            raise SourceUnavailable(
                "Sbazar could not resolve the postcode; no unfiltered search was fetched."
            ) from exc
        locality = f"municipality,{match['entity_id']}"
        radius = request.radius_km if request.radius_km is not None else 25
        warning = (
            f"Sbazar resolved postcode {request.location} to {match['suggest_first_row']} "
            f"using its first municipal suggestion and applied its native {radius} km filter. "
            "Postal areas may cover multiple places; exact listing distances are unverified."
        )
    url = build_search_url(request, locality=locality)
    response = await client.get(url, follow_redirects=False)
    response.raise_for_status()
    if "application/json" not in response.headers.get("content-type", "").lower():
        raise SourceUnavailable("Sbazar did not return a JSON search response.")
    try:
        payload = response.json()
    except ValueError as error:
        raise SourceUnavailable("Sbazar returned invalid JSON.") from error
    selected = filter_and_sort(parse_listings(payload), request)
    result = {
        "query": request.query,
        "count": len(selected),
        "listings": [listing.model_dump() for listing in selected],
    }
    if warning:
        result["warning"] = warning
    return result


async def search_listings(request: SearchRequest, client: httpx.AsyncClient | None = None) -> dict:
    """Fetch one JSON result page; never silently ignore geographic restrictions."""
    empty = {"query": request.query, "count": 0, "listings": []}
    if os.environ.get("SBAZAR_ACCESS_PERMITTED", "true") != "true":
        return empty | {
            "warning": (
                "Live Sbazar requests are disabled by configuration "
                "(SBAZAR_ACCESS_PERMITTED=false)."
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
