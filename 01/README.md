# Marketplace AI Agent — Stages 01–02

Stage 01 provides configuration validation, CLI diagnostics, and a development health
endpoint. Stage 02 adds a small Python FastMCP service for Bazoš search. The AI agent,
Sbazar, and agentgateway remain future work.

**Live Bazoš search is currently restricted.** The provider defaults to no external
requests. Operator permission and an allowing robots policy are required; otherwise
`search_listings` returns empty listings with a warning. No restrictions are bypassed.
See [Bazoš MCP](docs/bazos-mcp.md) for the verified source behavior and limitations.

## Original school assignment

> 📍 Napiš Python skript, který zavolá LLM API, použije nástroj (např. výpočetní funkci) a vrátí odpověď zpět LLM.
>
> 📄 Formát: Vypracovaný úkol odevzdejte ve formě zdrojového kódu. Projekt ideálně nahrajte na Github a odevzdejte link na Github repositáře.
>
> 📅 Deadline úkolu máš do 23. 11. 2026 23:59
>
> 📍 Maximální počet bodů, které můžeš získat je 100 bodů.

The assignment is not complete at this stage. Later stages will demonstrate:

```text
User → LLM → Tool call → MCP server → Tool result → LLM → Final response
```

## Current implementation

- Python 3.12+, uv, src layout, Hatchling, Pydantic and Pydantic Settings.
- Existing `version`, `doctor`, and `serve` CLI commands; `/health` on port 8080.
- Exactly one MCP tool: `search_listings`, using Streamable HTTP at `/mcp` on port 8001.
- httpx requests, BeautifulSoup listing summaries, local price validation and sorting.
- Two Compose services, `app` and `bazos-mcp`, using the same non-root Python Dockerfile.

There is no storage, ranking engine, additional MCP tool, frontend, gateway, or LLM
integration. `MARKETPLACE_MODE=demo|live` remains reserved for the future agent and does
not enable Bazoš access or return sample listings. `doctor` checks local initialization
and configuration without contacting services.

## Search tool

`search_listings(query, min_price=None, max_price=None, location=None, radius_km=None,
sort_by="relevance", limit=10)` accepts:

| Parameter | Meaning |
| --- | --- |
| `query` | Nonempty text, up to 256 characters; all Bazoš categories |
| `min_price`, `max_price` | Optional nonnegative integer CZK bounds, inclusive |
| `location` | Optional Czech postcode, e.g. `46001` or `460 01`; town names are rejected |
| `radius_km` | Integer 0–1000, requires location; location alone uses the source default of 25 km |
| `sort_by` | `relevance` (source order), `price_asc`, or `price_desc` |
| `limit` | Integer 1–50, default 10 |

Returns `{query, count, listings}` and an optional `warning`. Each listing contains
`title`, `price`, `currency`, `location`, `url`, and `description`. Unknown prices and
locations are `null`. Price bounds exclude unknown prices. Invalid input is an MCP tool
error; restricted/unavailable sources return empty listings and an explanatory warning.

Price sorting applies to the fetched first page before the limit; it does not promise
the cheapest/most expensive ads across the marketplace. Relevance keeps Bazoš matching
order, which includes date and TOP promotion. Geographic searches always warn that exact
distances cannot be verified. Missing confirmation of postcode/radius returns no listings.

## Local setup and CLI

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
cd 01
uv python install 3.12
cp .env.example .env  # First setup only; keep an existing local .env.
uv sync --locked
uv run --locked python -m marketplace_agent doctor
uv run --locked python -m marketplace_agent --help
uv run --locked python -m marketplace_agent version
uv run --locked python -m marketplace_agent serve
```

`serve` runs the development health endpoint at `http://localhost:8080/health`.
Run the MCP server separately with:

```bash
uv run --locked python -m marketplace_agent.mcp.bazos_server
```

It binds to `0.0.0.0:8001`, endpoint `/mcp`. `BAZOS_ACCESS_PERMITTED` must be exported
in the shell for local runs; the MCP module does not load `.env`. Leave it unset until
operator permission is obtained. It never overrides robots restrictions.

Stage 01 settings load environment variables, then optional `.env` in the current
working directory, then defaults. See [.env.example](.env.example) and
[development](docs/development.md). Optional service URLs are validated but never probed.

## Docker

With Docker Engine/Desktop and Compose v2.24+, run from `01/`:

```bash
docker compose up -d --build
docker compose ps
curl --fail http://localhost:8080/health
docker compose exec app python -m marketplace_agent doctor
docker compose logs bazos-mcp
docker compose down
```

Compose also works without `.env`. Only the app health port is published, on host
loopback. MCP is accessible inside Compose as `http://bazos-mcp:8001/mcp` with no
published host port. Both services use the existing Dockerfile, locked dependencies,
and native ARM64/AMD64 images. Source permission is independent of process readiness.
See [the MCP client example](docs/bazos-mcp.md#running-and-calling-the-tool).

## Tests and quality

```bash
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Tests cover Stage 01 startup/shutdown and configuration, search URLs, fixture HTML,
prices, filters, sorting, source failures/restrictions, and MCP discovery/invocation
including Streamable HTTP. No live marketplace access is needed. One live smoke test
is skipped by default; see [explicit opt-in](docs/bazos-mcp.md#testing).

## Technical outline

`domain/models.py` defines only `SearchRequest` and `Listing`. The independent
`providers/bazos.py` builds the global search form URL, checks access and robots,
fetches one page with a 15-second HTTP timeout, parses listing cards, verifies geographic
form values, filters prices, sorts, and limits results. `mcp/bazos_server.py` validates
inputs and delegates to that provider. There are no detail-page requests, retries,
caches, geocoding services, or fabricated results.

The TypeScript [reference](https://github.com/progresak/bazos-mcp-server/tree/main/src)
informed URL encoding and listing-card selectors; this implementation uses Python,
FastMCP, and the global category form rather than the reference's graphics-card path.
See [architecture](docs/architecture.md) for current boundaries and the planned system.

## Future implementation roadmap

1. **Stage 02 — Bazoš MCP:** implemented with one search tool, price and postcode/radius
   parameters, listing summaries, shared models, and offline tests. Live access remains
   restricted by the source; see [Bazoš MCP](docs/bazos-mcp.md).
2. **Stage 03 — Sbazar MCP:** implement the second independent FastMCP server,
   reusing shared interfaces and domain models.
3. **Stage 04 — agentgateway:** add the gateway to Compose, connect both MCP servers,
   and configure the external local LLM proxy.
4. **Stage 05 — Python AI Agent:** add LLM integration, MCP tool discovery, tool calling,
   tool result handling, orchestration, and an interactive CLI.
5. **Stage 06 — Integration and finalization:** add end-to-end tests, final documentation,
   assignment compliance verification, and a demonstration scenario showing the complete
   tool-call cycle.
