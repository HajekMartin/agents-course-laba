# Sbazar MCP — Stage 03

FastMCP exposes one `search_listings` tool over stateless Streamable HTTP at `/mcp`,
port 8002. It uses the same `SearchRequest` and `Listing` contract as Bazoš.

## Contract

Inputs are `query`, `min_price`, `max_price`, `location` (Czech postcode), `radius_km`,
`sort_by` (`relevance`, `price_asc`, `price_desc`) and `limit` (1–50, default 10).
Prices are inclusive nonnegative integer CZK bounds. Radius requires a postcode and
accepts 0–1000; when omitted with a postcode, 25 km is requested consistently with Bazoš.
The response contains `query`, `count`, `listings`, and optionally `warning`.

Listings preserve titles, explicit prices, marketplace URLs and source locality labels.
Unknown prices, locations and descriptions remain null. Negotiated prices are not zero-cost
items. Slugs/IDs are validated and duplicate IDs removed. Only summaries are fetched.

## Verified native search

Verified against the public frontend and live responses on 2026-11-08:

- `GET /api/v1/items/search` accepts `phrase`, `price_from`, `price_to` and `limit`.
- `GET /api/v2/localities/suggest?query=51101&include_zip=1` returns the source's ordered
  suggestions. Its first valid municipal suggestion was Turnov, ID 2751. IDs are resolved
  at runtime, never hardcoded in the provider.
- The frontend's request builder uses `locality=municipality,2751` and
  `radius_precision=30` for that municipality and radius. The provider uses those same
  native fields after resolving the requested postcode.
- A control search for iPhone 17 up to 17000 CZK returned 104 matches nationwide,
  zero at radius 0 around Turnov, and one at radius 30. These are verification-time counts,
  not fixtures, current availability guarantees or a claim that every match is a phone.

A postcode can cover several municipalities; the first source suggestion is an approximate
search origin. The response names that municipality and preserves an explicit warning.
Exact listing distances are not independently verified. Failed/empty locality resolution
never triggers an unfiltered nationwide fallback.

The endpoints are used by [Sbazar's public web application](https://www.sbazar.cz/), not a
promised stable third-party SDK. Their fields can change. Public searches are enabled by
default. The legacy `SBAZAR_ACCESS_PERMITTED=false` toggle explicitly disables requests;
its name is retained for compatibility. robots.txt is not an application access gate.
Actual HTTP 403/429, redirects, timeouts, CAPTCHA responses, invalid JSON or unknown payloads
return a warning. There are no authentication workarounds, retries or CAPTCHA bypasses.

One page of up to 60 summaries is fetched. Existing shared code filters prices, sorts that
page and applies the requested limit. Relevance preserves source order. There is no global
cheapest-price or exhaustive-search guarantee.

## Running and testing

```bash
docker compose up -d --build --wait
uv run --locked pytest tests/test_sbazar.py tests/test_bazos.py
uv run --locked ruff check .
uv run --locked ruff format --check .
SBAZAR_LIVE_SMOKE=true uv run --locked pytest tests/test_sbazar.py -m live -v
```

The optional last command uses the actual marketplace. Default tests use httpx mocks and
invented fixture data. They cover native radius translation (including 0 and the 25 km
default), locality lookup failures without filter relaxation, explicit source disabling,
price handling, malformed responses, HTTP failures, MCP schema/calls and Streamable HTTP.
The internal endpoint is `http://sbazar-mcp:8002/mcp`; the agent accesses it via agentgateway.
Local startup remains `python -m marketplace_agent.mcp.sbazar_server`.

## Reuse and attribution

The original [reference source](https://github.com/basta/sbazar-mcp/blob/main/src/index.ts)
informed the JSON normalization. Its MIT attribution is preserved in
[the upstream license notice](licenses/sbazar-mcp-MIT.txt). Native geography now uses the
verified frontend contract rather than the reference's local city-name substring filter.
No MCP tool, parameter, container, database or geocoding service was added.
