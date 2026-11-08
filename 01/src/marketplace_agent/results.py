"""Combine only the current search group; reuse existing price filtering and sorting."""

from dataclasses import dataclass, field

from marketplace_agent.agent_tools import MARKETPLACES
from marketplace_agent.domain.models import Listing, SearchRequest
from marketplace_agent.providers.common import filter_and_sort


class SourcedListing(Listing):
    source: str


@dataclass
class SearchResults:
    request: SearchRequest | None = None
    responses: dict[str, dict] = field(default_factory=dict)
    missing_sources: list[str] = field(default_factory=list)

    def add(self, source: str, request: SearchRequest, payload: dict) -> None:
        if request != self.request:
            self.responses.clear()
            self.request = request
        self.responses[source] = payload

    def combined(self, exclude_urls: list[str] | None = None) -> dict:
        if self.request is None:
            return {}
        listings = []
        warnings = [
            f"{MARKETPLACES[source]}: search tool unavailable." for source in self.missing_sources
        ]
        seen = set()
        for source, payload in self.responses.items():
            if warning := payload.get("error") or payload.get("warning"):
                warnings.append(f"{MARKETPLACES[source]}: {warning}")
            for data in payload.get("listings", []):
                listing = SourcedListing(**data, source=MARKETPLACES[source])
                if listing.url in seen or listing.url in (exclude_urls or []):
                    continue
                seen.add(listing.url)
                listings.append(listing)
        selected = filter_and_sort(listings, self.request)
        return {
            "search": self.request.model_dump(),
            "listings": [listing.model_dump() for listing in selected],
            "count": len(selected),
            "searched_sources": [MARKETPLACES[source] for source in self.responses],
            "pages_scanned": sum(
                payload.get("pages_scanned", 0) for payload in self.responses.values()
            ),
            "filtered_count": sum(
                payload.get("filtered_count", 0) for payload in self.responses.values()
            ),
            "has_more": any(payload.get("has_more", False) for payload in self.responses.values()),
            "warnings": warnings,
            "incomplete": bool(warnings),
            "coverage": "Only fetched source pages; not an exhaustive marketplace search.",
            "geography_verified": False if self.request.location else None,
        }


def model_result(payload: dict) -> dict:
    """Bound ad text before it enters LLM context; keep original URLs and factual fields."""
    result = dict(payload)
    result["listings"] = [
        dict(item) | {"description": (item.get("description") or "")[:600]}
        for item in payload.get("listings", [])
    ]
    return result


def render_results(payload: dict) -> str:
    """Render the canonical ordered listings without asking the model to copy factual data."""
    if not payload:
        return ""
    lines = []
    if payload.get("pages_scanned"):
        lines.append(
            f"Checked {payload['pages_scanned']} source page(s); "
            f"filtered {payload['filtered_count']} obvious irrelevant ads before sorting."
        )
    if lookup := payload.get("postcode_lookup"):
        lines.append(
            f"Search postcode: {lookup['postcode']} "
            f"([source]({lookup['source_url']}), {lookup['place']})."
        )
    for index, listing in enumerate(payload["listings"], 1):
        price = (
            f"{listing['price']:,}".replace(",", " ") + f" {listing['currency']}"
            if listing["price"] is not None
            else "price unavailable"
        )
        location = f" | {listing['location']}" if listing["location"] else ""
        lines.append(f"{index}. {listing['title']} — {price} | {listing['source']}{location}")
        lines.append(f"   [Original listing]({listing['url']})")
        if listing["description"]:
            description = " ".join(listing["description"].split())[:240]
            lines.append(f"   {description}")
    for warning in payload["warnings"]:
        lines.append(f"WARNING: {warning}")
    if payload.get("search", {}).get("location"):
        lines.append(
            "WARNING: Exact geographic distances are unverified; these are source candidates."
        )
    if payload["listings"]:
        lines.append("Coverage: fetched source pages only; no global completeness guarantee.")
    elif payload["incomplete"]:
        lines.append("No verified matching listings available; the search was incomplete.")
    else:
        lines.append("No matching listings returned from the fetched pages.")
    return "\n".join(lines)
