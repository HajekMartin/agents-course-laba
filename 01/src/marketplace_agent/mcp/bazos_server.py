"""Expose exactly one Bazos search tool over Streamable HTTP."""

from fastmcp import FastMCP

from marketplace_agent.domain.models import SearchRequest, SortOrder
from marketplace_agent.providers import bazos

mcp = FastMCP("Bazos MCP", strict_input_validation=True)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
async def search_listings(
    query: str,
    min_price: int | None = None,
    max_price: int | None = None,
    location: str | None = None,
    radius_km: int | None = None,
    sort_by: SortOrder = "relevance",
    limit: int = 10,
) -> dict:
    """Search all Bazos categories; prices in CZK, location as Czech postcode (46001).

    Radius requires location; location alone uses 25 km. Limit is 1..50, radius 0..1000.
    Relevance preserves source order; prices are sorted within one fetched result page.
    Returns query, count, listings (title, price, currency, location, url, description),
    and an optional warning about access or unverifiable geographic filtering.
    """
    request = SearchRequest(
        query=query,
        min_price=min_price,
        max_price=max_price,
        location=location,
        radius_km=radius_km,
        sort_by=sort_by,
        limit=limit,
    )
    return await bazos.search_listings(request)


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=8001,
        path="/mcp",
        stateless_http=True,
        json_response=True,
    )
