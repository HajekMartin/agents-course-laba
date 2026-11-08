"""Small source-independent helpers shared by the marketplace providers."""

from marketplace_agent.domain.models import Listing, SearchRequest
from marketplace_agent.providers.matching import matches_product

USER_AGENT = "MarketplaceCourseBot/0.1"


class SourceUnavailable(RuntimeError):
    """Access is restricted or the source cannot be read reliably."""


def filter_and_sort(listings: list[Listing], request: SearchRequest) -> list[Listing]:
    """Recheck price bounds, keep unknown prices last, preserve source order for relevance."""
    listings = [
        listing
        for listing in listings
        if (
            request.min_price is None
            or (listing.price is not None and listing.price >= request.min_price)
        )
        and (
            request.max_price is None
            or (listing.price is not None and listing.price <= request.max_price)
        )
    ]
    listings = [listing for listing in listings if matches_product(listing.title, request.query)]
    listings = list({listing.url: listing for listing in listings}.values())
    if request.sort_by != "relevance":
        direction = -1 if request.sort_by == "price_desc" else 1
        listings.sort(key=lambda listing: (listing.price is None, direction * (listing.price or 0)))
    return listings[: request.limit]


def search_result(request, listings, pages_scanned, has_more, warning=None) -> dict:
    """Apply relevance before final price ordering/limit and disclose bounded coverage."""
    selected = filter_and_sort(listings, request)
    warnings = [warning] if warning else []
    if has_more:
        warnings.append(
            f"Scanned {pages_scanned} page(s); further source results were not fetched."
        )
    result = {
        "query": request.query,
        "count": len(selected),
        "listings": [listing.model_dump() for listing in selected],
        "pages_scanned": pages_scanned,
        "has_more": has_more,
        "scanned_count": len(listings),
        "filtered_count": sum(not matches_product(item.title, request.query) for item in listings),
    }
    if warnings:
        result["warning"] = " ".join(warnings)
    return result
