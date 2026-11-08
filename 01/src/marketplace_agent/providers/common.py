"""Small source-independent helpers shared by the marketplace providers."""

from marketplace_agent.domain.models import Listing, SearchRequest

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
    if request.sort_by != "relevance":
        direction = -1 if request.sort_by == "price_desc" else 1
        listings.sort(key=lambda listing: (listing.price is None, direction * (listing.price or 0)))
    return listings[: request.limit]
