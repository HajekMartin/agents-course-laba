# Marketplace AI Agent — Stages 01–04

Stage 01 provides configuration validation, CLI diagnostics, and a development health
endpoint. Stage 02 adds a small Python FastMCP service for Bazoš search. Stage 03 adds
the independent Sbazar MCP using the same tool contract. Stage 04 federates both servers
through agentgateway and connects the external local Unsloth Studio API. The AI agent
remains future work.

**Live Bazoš search is currently restricted.** The provider defaults to no external
requests. Operator permission and an allowing robots policy are required; otherwise
`search_listings` returns empty listings with a warning. No restrictions are bypassed.
See [Bazoš MCP](docs/bazos-mcp.md) for the verified source behavior and limitations.

**Live Sbazar search is also restricted and unverified.** Its current robots policy
disallows automated access. The JSON adapter is tested with mocks; geographic requests
return no listings and an explicit unsupported-filter warning. See
[Sbazar MCP](docs/sbazar-mcp.md) for endpoint verification limits and usage.

Status: Stage 01 completed; Stage 02 completed; Stage 03 completed (live marketplace access
restricted); Stage 04 completed and verified with Docker, fixture backends and live Unsloth;
Stage 05 AI Agent planned; Stage 06 Integration and finalization planned.

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
- Exactly one `search_listings` tool per MCP server, using Streamable HTTP at `/mcp`:
  Bazoš on port 8001 and Sbazar on 8002.
- httpx requests, Bazoš HTML/Sbazar JSON summaries, shared price validation and sorting.
- Four Compose services: `app`, `bazos-mcp`, and `sbazar-mcp` share the existing non-root
  Python Dockerfile; `agentgateway` uses the official pinned v1.7.0 image and digest.
- One MCP gateway endpoint at `http://localhost:3000/mcp`, exposing the discovered names
  `bazos_search_listings` and `sbazar_search_listings` with their original schemas.
- OpenAI-compatible chat completions at `http://localhost:3001/v1/chat/completions`,
  routed only to the configured local Unsloth model. Read-only UI at `http://localhost:3002/ui/`.

There is no AI agent, tool-calling orchestration, storage, ranking engine, additional MCP
tool, or application frontend. `MARKETPLACE_MODE=demo|live` remains reserved for the future agent and does
not enable marketplace access or return sample listings. `doctor` checks local initialization
and configuration without contacting services.
Use `python -m marketplace_agent.gateway_check` inside Compose for explicit online
diagnostics, including MCP initialization/discovery/invocation and direct/proxied LLM requests.

## Search tool

`search_listings(query, min_price=None, max_price=None, location=None, radius_km=None,
sort_by="relevance", limit=10)` accepts:

| Parameter | Meaning |
| --- | --- |
| `query` | Nonempty text, up to 256 characters; all marketplace categories |
| `min_price`, `max_price` | Optional nonnegative integer CZK bounds, inclusive |
| `location` | Optional Czech postcode, e.g. `46001` or `460 01`; town names are rejected by the shared contract; Sbazar returns an unsupported-filter warning |
| `radius_km` | Integer 0–1000, requires location; Bazoš location alone uses 25 km; Sbazar geographic requests return no listings and a warning |
| `sort_by` | `relevance` (source order), `price_asc`, or `price_desc` |
| `limit` | Integer 1–50, default 10 |

Returns `{query, count, listings}` and an optional `warning`. Each listing contains
`title`, `price`, `currency`, `location`, `url`, and `description`. Unknown prices and
locations are `null`. Missing Sbazar descriptions are `null`; Bazoš retains empty strings.
Price bounds exclude unknown prices. Invalid input is an MCP tool
error; restricted/unavailable sources return empty listings and an explanatory warning.

Price sorting applies to the fetched first page before the limit; it does not promise
the cheapest/most expensive ads across the marketplace. Relevance keeps source order;
Bazoš ordering includes date and TOP promotion. Bazoš geographic searches warn that exact
distances cannot be verified; missing form confirmation returns no listings. Sbazar
rejects geographic restrictions with an explicit warning and no external requests.

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
uv run --locked python -m marketplace_agent.mcp.sbazar_server  # In another terminal.
```

They bind to `0.0.0.0:8001` and `0.0.0.0:8002`, endpoint `/mcp`. Permission flags
`BAZOS_ACCESS_PERMITTED` / `SBAZAR_ACCESS_PERMITTED` must be exported in the shell for
local runs; MCP modules do not load `.env`. Leave them unset until operator permission
is obtained. They never override robots restrictions.

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
docker compose exec app python -m marketplace_agent.gateway_check --mcp-only --schemas
docker compose exec app python -m marketplace_agent.gateway_check
docker compose logs bazos-mcp
docker compose logs sbazar-mcp
docker compose down
```

Compose also starts without `.env`; MCP works and the LLM route requires actual Unsloth
settings before use. Published app/gateway ports bind only to host loopback.
Bazoš is accessible inside Compose as `http://bazos-mcp:8001/mcp` with no
published host port. Sbazar is internal at `http://sbazar-mcp:8002/mcp`. All services
use locked dependencies and native ARM64/AMD64 images. Source permission is independent
of process readiness. agentgateway joins the same default Compose network.
See [the MCP client example](docs/bazos-mcp.md#running-and-calling-the-tool) and
[Sbazar discovery and invocation](docs/sbazar-mcp.md#running-and-testing) for calls
from inside Compose.

The LLM already runs independently on the Mac; Compose never downloads or starts it.
Set `UNSLOTH_BASE_URL` (using `host.docker.internal` and the actual port), `UNSLOTH_MODEL`
(a loaded ID from `/v1/models`), and `UNSLOTH_API_KEY` in your ignored `.env`.
`LLM_TIMEOUT` sets the request timeout in seconds. No cloud fallback is configured.
See [agentgateway and Unsloth](docs/agentgateway.md) for model discovery, authentication,
Docker networking, endpoints, integration tests, and troubleshooting.

## Tests and quality

```bash
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
# Optional real gateway tests with fixture marketplaces and a mock LLM; no Unsloth needed:
GATEWAY_DOCKER_TESTS=true uv run --locked pytest tests/integration/test_agentgateway.py
```

Tests cover Stage 01 startup/shutdown and configuration, search URLs, fixture HTML/JSON,
prices, filters, sorting, source failures/restrictions, and MCP discovery/invocation
including Streamable HTTP and equivalent schemas. No live marketplace access is needed.
Gateway tests additionally cover configuration, namespacing, real MCP calls, mock LLM
routing/authentication/parameter preservation, timeouts, and unavailable upstreams.
Docker and live Unsloth tests are opt-in. Two marketplace smoke tests are also skipped
by default; see [Bazoš opt-in](docs/bazos-mcp.md#testing)
and [Sbazar opt-in](docs/sbazar-mcp.md#running-and-testing).

## Technical outline

`domain/models.py` defines only `SearchRequest` and `Listing`. The independent
`providers/bazos.py` builds the global search form URL, checks access and robots,
fetches one page with a 15-second HTTP timeout, parses listing cards, verifies geographic
form values, filters prices, sorts, and limits results. `mcp/bazos_server.py` validates
inputs and delegates to that provider. `providers/sbazar.py` parses one JSON page using
the reference endpoint, subject to source access restrictions. `mcp/sbazar_server.py`
exposes the same tool parameters and response fields. `providers/common.py` reuses the
existing Bazoš price filtering, sorting and robots check. There are no detail-page
requests, retries, caches, geocoding services, or fabricated results.

The TypeScript [reference](https://github.com/progresak/bazos-mcp-server/tree/main/src)
informed URL encoding and listing-card selectors; this implementation uses Python,
FastMCP, and the global category form rather than the reference's graphics-card path.
See [architecture](docs/architecture.md) for current boundaries and the planned system.
The MIT-licensed [Sbazar reference](https://github.com/basta/sbazar-mcp/blob/main/src/index.ts)
informed JSON request parameters and data mapping; its attribution and endpoint
verification limits are documented in [Sbazar MCP](docs/sbazar-mcp.md).

## Future implementation roadmap

1. **Stage 01 — Project setup:** completed with configuration, CLI, health server and Docker.
2. **Stage 02 — Bazoš MCP:** completed with one search tool, price and postcode/radius
   parameters, listing summaries, shared models, and offline tests. Live access remains
   restricted by the source; see [Bazoš MCP](docs/bazos-mcp.md).
3. **Stage 03 — Sbazar MCP:** completed with the same tool schema, shared models/helpers,
   JSON adapter and tests. Live access remains restricted; geography explicitly unsupported.
4. **Stage 04 — agentgateway:** completed with static MCP federation, distinct search-tool
   names, local Unsloth proxy, diagnostics and isolated Docker integration tests.
5. **Stage 05 — Python AI Agent (planned):** add LLM integration, MCP tool discovery, tool calling,
   tool result handling, orchestration, and an interactive CLI.
6. **Stage 06 — Integration and finalization (planned):** add end-to-end tests, final documentation,
   assignment compliance verification, and a demonstration scenario showing the complete
   tool-call cycle.
