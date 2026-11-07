"""Expose exactly one Sbazar search tool over Streamable HTTP."""

from fastmcp import FastMCP

from marketplace_agent.domain.models import SearchRequest, SortOrder
from marketplace_agent.providers import sbazar

mcp = FastMCP("Sbazar MCP", strict_input_validation=True)


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
    """Search Sbazar listing summaries; inclusive prices in CZK, limit 1..50.

    Relevance preserves source order; prices are sorted within one fetched result page.
    Location accepts Czech postcodes (46001), matching Bazos validation. Geographic
    filtering is currently unsupported: location/radius returns no listings and a warning.
    Returns query, count, listings (title, price, currency, location, url, description),
    and an optional warning about source restrictions, unsupported filters or failures.
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
    return await sbazar.search_listings(request)


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=8002,
        path="/mcp",
        stateless_http=True,
        json_response=True,
    )
