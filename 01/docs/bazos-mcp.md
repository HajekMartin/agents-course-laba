# Bazoš MCP — Stage 02

FastMCP exposes one `search_listings` tool over stateless Streamable HTTP at `/mcp`,
port 8001. It searches public listing summaries across all categories.

## Contract

Inputs are `query`, `min_price`, `max_price`, `location` (Czech postcode), `radius_km`,
`sort_by` (`relevance`, `price_asc`, `price_desc`) and `limit` (1–50, default 10).
Query length is 1–256 characters. Price bounds are inclusive nonnegative integer CZK
amounts. Postcodes are normalized to five digits. Radius is 0–1000 and requires a postcode;
location alone uses the source's default 25 km. Invalid inputs fail before HTTP.

The response contains `query`, `count`, `listings` and optionally `warning`. Each listing
preserves its title, explicit price, currency, location, original URL and description.
Unknown prices/locations are null; missing descriptions are empty strings. Unknown prices
fail a requested price bound and sort last. Only validated Bazoš listing URLs are returned.

## Verified source behavior

The [global form](https://www.bazos.cz/) submits `/search.php` with `hledat`, `rubriky=www`,
`cenaod`, `cenado`, `hlokalita`, `humkreis` and `kitx=ano`. Cards use `.inzeraty`,
`h2.nadpis a`, `.inzeratycena`, `.inzeratylok` and `.popis`.

On 2026-11-08 a live user-requested search for iPhone 17 up to 17000 CZK, postcode 51101,
radius 30 km returned HTTP 200, actual listings and form fields echoing those filters.
This verifies retrieval and native filter submission, not exact distances from individual
addresses. A missing query/postcode/radius confirmation returns a warning instead of
silently presenting an unfiltered page. Geographic results always preserve this limitation.

Public user-requested searches are enabled by default. The legacy
`BAZOS_ACCESS_PERMITTED=false` toggle explicitly disables requests. robots.txt is not an
application access gate. Its crawler directives are distinct from HTTP authorization;
see [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html). This is a bounded search
client, not an indexing crawler. Actual HTTP errors, redirects, rate limits and access
challenges are reported without bypasses or retries.

Only one result page is fetched. The existing shared helper filters/sorts that page and
applies the requested limit. Relevance preserves source order, which can include promoted
items. There is no claim of global completeness or globally cheapest listings.

## Running and testing

```bash
docker compose up -d --build --wait
uv run --locked pytest tests/test_bazos.py
uv run --locked ruff check .
uv run --locked ruff format --check .
BAZOS_LIVE_SMOKE=true uv run --locked pytest tests/test_bazos.py -m live -v
```

The optional last command uses live Bazoš. Default tests use invented HTML and httpx mocks,
including query/location form confirmation, prices, malformed pages, HTTP failures,
explicit disabling, MCP registration/calls and the Streamable HTTP endpoint.
The endpoint `http://bazos-mcp:8001/mcp` is internal to Compose. The Python agent accesses
it via agentgateway. Local startup remains `python -m marketplace_agent.mcp.bazos_server`.

## Reuse

`domain/models.py` holds shared validation, `providers/bazos.py` handles bounded HTTP and
card parsing, and `providers/common.py` holds source-independent price filtering/sorting.
The [reference index.ts](https://github.com/progresak/bazos-mcp-server/blob/main/src/index.ts)
and [bazos.ts](https://github.com/progresak/bazos-mcp-server/blob/main/src/bazos.ts) informed
the original adapter. No detail scraping, persistence, new tool or container was added.
