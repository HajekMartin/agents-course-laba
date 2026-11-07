"""Small source-independent helpers shared by the marketplace providers."""

import re
from urllib.parse import unquote, urlsplit
from urllib.robotparser import RobotFileParser

from marketplace_agent.domain.models import Listing, SearchRequest

USER_AGENT = "MarketplaceCourseBot/0.1"


class SourceUnavailable(RuntimeError):
    """Access is restricted or the source cannot be read reliably."""


def robots_allows(robots: str, url: str, *, source: str = "Bazos") -> bool:
    """Apply robots rules, including wildcard paths (unsupported by can_fetch)."""
    if "user-agent:" not in robots.lower():
        raise SourceUnavailable(
            f"{source} robots.txt could not be verified; search was not fetched."
        )
    parser = RobotFileParser()
    parser.parse(robots.splitlines())
    entry = next(
        (entry for entry in parser.entries if entry.applies_to(USER_AGENT)), parser.default_entry
    )
    if entry is None:
        return True
    parts = urlsplit(url)
    target = unquote(parts.path + (f"?{parts.query}" if parts.query else ""))
    matches = []
    for rule in entry.rulelines:
        path = unquote(rule.path)
        anchored = path.endswith("$")
        path = path.removesuffix("$") if anchored else path
        pattern = "^" + re.escape(path).replace(r"\*", ".*") + ("$" if anchored else "")
        if re.search(pattern, target):
            matches.append((len(path.replace("*", "")), rule.allowance))
    return max(matches, default=(0, True))[1]


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
