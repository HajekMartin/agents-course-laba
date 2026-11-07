# Sbazar MCP — Stage 03

Python FastMCP exposes exactly one `search_listings` tool over stateless Streamable
HTTP at `/mcp`, port 8002, bound to `0.0.0.0`. The server needs neither LLM nor gateway.
The implementation is tested offline; live search is currently restricted and unverified.

## Contract and filters

The signature and MCP input/output schemas match Bazoš:

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

The existing shared `SearchRequest` strips text (1–256 characters), validates
nonnegative integer CZK bounds with minimum <= maximum, normalizes Czech postcodes
(`460 01` to `46001`), requires location for radius (integer 0–1000), and limits results
to 1–50. City/municipality names such as Turnov, Liberec or Praha are rejected, preserving
the established Bazoš contract. Invalid arguments produce MCP tool errors before HTTP.

The reference JSON request uses `phrase`, `price_from` and `price_to`; either price bound,
both, or neither can be supplied. One page of up to 60 summaries is requested before
local filtering, sorting and the final limit. Bounds are inclusive. Only explicit
nonnegative integer prices are accepted; missing, malformed and negotiated prices are
`null`, including `price: 0` with `price_by_agreement: true`. Unknown prices fail any
price bound and sort last. Equal prices preserve source order. `relevance` preserves
source ordering; there is no AI ranking or claim of globally cheapest results.

**Geographic restriction is unsupported by this adapter.** The reference only applies a
city-name substring filter locally; it has no native postcode/radius request parameters
or distance calculation. No usable native geographic contract could be verified under
the current access policy. Bazoš has form confirmation but no reusable coordinates or
geocoding utility. Any supplied postcode (with or without radius, including radius 0)
therefore returns empty listings and an explicit warning without HTTP requests. The
adapter never silently ignores location or presents unknown distances as verified.

Returns `{query, count, listings}` with optional `warning`. Each shared `Listing` has
`title`, numeric-or-null `price`, `currency: "CZK"`, `location`, `url`, and `description`.
Missing locations/descriptions are `null`; Bazoš keeps its existing empty-string
description behavior. The shared description type now allows either. Listings without
a usable title, ID or safe source slug are skipped; duplicate IDs are removed. Locations
join the supplied quarter, municipality and district labels without duplicates. URLs
use the listing ID and source slug, handling slugs that already contain the ID. No
detail pages are fetched and numbers in titles/descriptions never become prices.

## Access verification and limitations

Checked on 2026-11-07:

- Read the actual [reference source](https://github.com/basta/sbazar-mcp/blob/main/src/index.ts)
  and its [smoke client](https://github.com/basta/sbazar-mcp/blob/main/test_sbazar.py).
  They use GET `https://www.sbazar.cz/api/v1/items/search` and a `results` array containing
  `id`, `seo_name`, `name`, `price`, `price_by_agreement`, `locality` and `description`.
  This is a reference-based endpoint, **not a verified supported public API**.
- Retrieved current [robots.txt](https://www.sbazar.cz/robots.txt): `User-agent: *`
  disallows `/`. The provider identifies itself as `MarketplaceCourseBot/0.1`; it does
  not impersonate a browser or an allowed search crawler. No live search was fetched.
- Inspected the current [terms](https://o-seznam.cz/napoveda/sbazar/jak-inzerovat/smluvni-podminky/smluvni-podminky-sbazar-a-v-mobilni-aplikaci/)
  and [buying help](https://o-seznam.cz/napoveda/sbazar/jak-nakupovat/). They do not
  establish a supported public search API or a verified kilometer-radius contract.

Live access defaults to disabled, with no network requests. Only with operator permission
may `SBAZAR_ACCESS_PERMITTED=true` enable the robots check; it never overrides a disallow.
The current policy still prevents search. **The endpoint's continued functionality,
live text matching, native price filters and payload compatibility could not be
verified.** Mock tests validate the adapter, not the marketplace. Recheck these only
when automated access is permitted; do not treat Stage 03 as verified live search.

HTTP errors (including redirects, 403 and 429), timeouts, unavailable robots, wrong
content types, malformed JSON and unrecognized payloads return empty listings with a
warning. An explicit empty `results` array is a successful empty search. There are no
retries, authentication/CAPTCHA workarounds, HTML fallbacks, caches or pagination.

The reference is MIT licensed, copyright (c) 2026 basta. This Python implementation
reuses technical ideas rather than TypeScript source; the upstream notice is preserved
in [sbazar-mcp-MIT.txt](licenses/sbazar-mcp-MIT.txt). No Node.js dependency or item-details
tool was added.

## Running and testing

From `01/`:

```bash
docker compose up -d --build
docker compose ps
docker compose logs sbazar-mcp
```

Both MCP services share the existing Dockerfile and Compose network. Endpoints are
internal only: `http://bazos-mcp:8001/mcp` and `http://sbazar-mcp:8002/mcp`.
Healthchecks discover the MCP tool without requesting marketplace data.

Discover and invoke Sbazar from inside Compose:

```bash
docker compose exec -T sbazar-mcp python - <<'PY'
import asyncio
from fastmcp import Client

async def main():
    async with Client("http://sbazar-mcp:8002/mcp") as client:
        print([tool.name for tool in await client.list_tools()])
        result = await client.call_tool("search_listings", {
            "query": "iPhone 15", "min_price": 4000, "max_price": 15000,
            "sort_by": "price_asc", "limit": 5,
        })
        print(result.data)

asyncio.run(main())
PY
```

Under the current policy, expect an empty result with an access warning; this still
verifies the MCP discovery/invocation path. For Bazoš use the other endpoint.
Local startup: `uv run --locked python -m marketplace_agent.mcp.sbazar_server`.
Like Bazoš, the module reads its permission flag from the process environment; local
runs do not load `.env`. Compose injects optional `.env` values.

```bash
uv run --locked pytest tests/test_sbazar.py tests/test_bazos.py
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Normal tests use httpx mocks and an invented JSON fixture. They cover request parameters,
missing/invalid data, inclusive price bounds, sorting before limit, unsupported geography,
source failures/restrictions, identical MCP schemas, tool calls and Streamable HTTP.

Only after obtaining operator permission, optionally run:

```bash
SBAZAR_ACCESS_PERMITTED=true SBAZAR_LIVE_SMOKE=true uv run --locked pytest tests/test_sbazar.py -m live -v
```

The smoke test checks robots first and skips if disallowed; a skip does not establish
live integration success. Both flags must be exported or supplied in the shell.

## Reuse

`providers/sbazar.py` contains only JSON request/parsing and source access behavior.
`domain/models.py` supplies the existing request validation and listing fields.
`providers/common.py` holds the Bazoš price filter/sort and robots helpers, extracted
without changing Bazoš behavior. `mcp/sbazar_server.py` mirrors the Bazoš single-tool
wrapper. This provider introduces no geographic subsystem or storage. The Stage 05
[Python agent](agent.md) consumes it through the existing Stage 04 gateway.
