# Bazoš MCP — Stage 02

A small Python FastMCP service exposes exactly one tool, `search_listings`, over
Streamable HTTP at `/mcp`, port 8001. It searches listing summaries across categories.
HTTP is stateless with JSON responses; no persistent MCP sessions are needed.
The base Stage 01 application remains independent.

## Inputs and output

```python
search_listings(
    query: str,
    min_price: int | None = None,
    max_price: int | None = None,
    location: str | None = None,
    radius_km: int | None = None,
    sort_by: Literal["relevance", "price_asc", "price_desc"] = "relevance",
    limit: int = 10,
) -> dict
```

Text is stripped and must contain 1–256 characters. Prices are nonnegative integers,
inclusive, with minimum no greater than maximum. `location` accepts a Czech postcode
(`46001` or `460 01`), normalized to five digits. Town names are rejected because they
would require the site's restricted postcode autocomplete. Radius is an integer 0–1000
and requires a postcode; location alone uses the form's default 25 km. Limit is 1–50.
Invalid parameters produce an MCP tool error before HTTP requests.

The JSON-compatible result has `query`, `count` (returned listings, not total matches),
and `listings`. Every listing has `title`, `price`, `currency` (`CZK`), `location`, `url`,
and `description`. Unknown prices/locations are `null`; absent descriptions are empty
strings. Listings with unknown prices are excluded when a price bound is requested.
An optional `warning` explains restrictions, source failure, or geographic uncertainty.
No sample listing data is returned by the running service.

## Running and calling the tool

From `01/`, using the existing Dockerfile:

```bash
docker compose up -d --build
docker compose logs bazos-mcp
```

The endpoint `http://bazos-mcp:8001/mcp` is internal to Compose. No MCP port is published.
To discover and call it from another container in that network:

```bash
docker compose exec -T bazos-mcp python - <<'PY'
import asyncio
from fastmcp import Client

async def main():
    async with Client("http://bazos-mcp:8001/mcp") as client:
        print([tool.name for tool in await client.list_tools()])
        result = await client.call_tool("search_listings", {
            "query": "horské kolo", "min_price": 3000, "max_price": 15000,
            "location": "46001", "radius_km": 25, "sort_by": "price_asc", "limit": 5,
        })
        print(result.data)

asyncio.run(main())
PY
```

Local startup: `uv run --locked python -m marketplace_agent.mcp.bazos_server`.
This binds to `0.0.0.0:8001`. Local MCP runs read `BAZOS_ACCESS_PERMITTED` from the process
environment; Compose reads it from optional `.env`. `MARKETPLACE_MODE` does not enable
source access. All tests use mocks unless the live smoke test is explicitly enabled.

## Source verification and access limitations

Inspected on 2026-11-07:

- The [global form](https://www.bazos.cz/) submits GET `/search.php`, with `hledat`,
  `rubriky=www` (all categories), `cenaod`, `cenado`, `hlokalita` (postcode/place),
  `humkreis` (km, default 25), and `kitx=ano`.
- The [category page](https://pc.bazos.cz/) still uses `.inzeraty`, `h2.nadpis a`,
  `.inzeratycena`, `.inzeratylok`, and `.popis`. The price header submits `order=1`.
  Exact ordering/toggle semantics were not verified through restricted searches;
  this provider omits `order` and sorts the fetched listings locally.
- Bazoš [terms](https://www.bazos.cz/podminky.php) restrict unofficial applications and
  require approval for direct API integration. Obtain operator permission before
  setting `BAZOS_ACCESS_PERMITTED=true`; the default is disabled and makes no requests.
- [robots.txt](https://www.bazos.cz/robots.txt) currently disallows `/search.php` and
  wildcard query paths for search, location, radius, sorting, and price. With permission
  enabled, the provider still checks robots and returns a warning without fetching a
  disallowed search. There is no robots override or CAPTCHA bypass.

The live search response, filter behavior, and result coverage could therefore not be
verified. URL construction is based on current public forms, not proof of successful
live filtering. Offline fixtures validate the implementation, not the marketplace.
Full live operation requires an access policy that permits these requests.

Geographic requests must be echoed by the returned form; otherwise no listings are
returned. Even echoed values do not prove strict distance: listing cards contain no
coordinates, and postcode-centered filtering may be approximate. Every geographic
response warns about this; no distances or coordinates are invented.
Nonempty results also require the form to echo the requested text query, so a generic
page cannot silently pass as a successful search.

Only one result page is fetched; no pagination or global cheapest-price claim.
`relevance` preserves the source's matching order. Bazoš documents default ordering by
date and TOP promotion, not semantic relevance. Unknown prices sort last in both price
directions. Descriptions are source snippets and may be truncated by Bazoš. Layout
changes, HTTP errors, redirects, rate limiting, unavailable robots, or unrecognized
HTML return empty listings with a warning; there are no retries or fallback scraping.

## Technical implementation

- `domain/models.py`: two small Pydantic models, no MCP dependency.
- `providers/bazos.py`: permission checks, a 15-second httpx timeout, global URL encoding,
  BeautifulSoup's standard HTML parser, safe marketplace links, deduplication and
  geographic form confirmation.
- `providers/common.py`: existing robots and price filtering/sorting helpers, now also
  reused by Sbazar without changing Bazoš behavior.
- `mcp/bazos_server.py`: the single tool and Streamable HTTP entry point.

The [reference index.ts](https://github.com/progresak/bazos-mcp-server/blob/main/src/index.ts)
and [bazos.ts](https://github.com/progresak/bazos-mcp-server/blob/main/src/bazos.ts) informed
the adapter and card selectors. The graphics-card path and stdio-only transport were
replaced by global search and Python FastMCP HTTP. No ranking engine, persistence,
detail tool, geocoding, gateway, frontend, or LLM agent is implemented.
Stage 03 adds the independent [Sbazar MCP](sbazar-mcp.md) with the same tool contract.

## Testing

```bash
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Fixture HTML contains invented test data; httpx MockTransport supplies all marketplace
responses. Tests cover URL/filter handling, missing values, price parsing/filtering,
sorting/limit, empty/invalid pages, access failures, MCP registration/calls, and the
HTTP endpoint using ASGITransport. Stage 01 tests still cover the CLI and health server.

Only after operator permission, explicitly enable the optional live smoke test:

```bash
BAZOS_ACCESS_PERMITTED=true BAZOS_LIVE_SMOKE=true uv run --locked pytest -m live -v
```

It checks robots first and skips if search remains disallowed. Both flags must be set
in the shell; a flag in `.env` alone does not enable this test. Neither flag bypasses
source restrictions. The regular test suite never needs live Bazoš access.
