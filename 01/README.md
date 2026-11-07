# Marketplace AI Agent — Lesson 1

A Python project foundation for an AI agent that will search [Bazoš](https://www.bazos.cz)
and [Sbazar](https://www.sbazar.cz). **Stage 01 implements initialization only.**
The application currently provides configuration validation, CLI diagnostics, and a
development health endpoint. It makes no external service calls.

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

## Planned functionality and architecture

The agent will search both marketplaces, filter by price and location/radius, retrieve
listing details, and return structured results through two independent FastMCP servers.
Marketplace providers will also be usable directly from Python, independently of MCP.
agentgateway will connect the Python agent to an external locally hosted
OpenAI-compatible LLM and the MCP servers.

```text
User
  |
  v
Python Agent
  |
  v
agentgateway
  |            |
  v            v
Local LLM   MCP Gateway
               |
        +------+------+
        |             |
        v             v
    Bazoš MCP     Sbazar MCP
```

See [architecture](docs/architecture.md) for responsibilities and future module boundaries.

## Technology stack and current status

| Component | Stage 01 status |
| --- | --- |
| Python 3.12+, uv, src layout, Hatchling packaging | Implemented |
| Pydantic and Pydantic Settings | Implemented configuration |
| argparse CLI, standard-library HTTP health server | Implemented |
| pytest, Ruff | Configured; tests cover current behavior |
| Docker, Docker Compose | One base `app` service; native ARM64/AMD64 builds |
| FastMCP, marketplace providers and domain models | Planned; no dependency or implementation yet |
| agentgateway, local LLM integration, AI orchestration | Planned; no running services or integration yet |

`MARKETPLACE_MODE=demo` and `live` are reserved configuration values. Neither currently
performs searches or returns simulated listings. No scraping or tool calling is implemented.

## Directory structure

```text
01/
├── README.md
├── pyproject.toml
├── uv.lock
├── .python-version
├── .env.example
├── .gitignore
├── .dockerignore
├── Dockerfile
├── compose.yaml
├── src/marketplace_agent/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   └── health.py
├── tests/test_project_setup.py
└── docs/
    ├── architecture.md
    └── development.md
```

Future `agent`, `domain`, `providers`, `services`, and `mcp` packages will be created when
they have working code. `config/agentgateway.yaml` will be added with the actual gateway
deployment in Stage 04. There are no empty feature placeholders or fake gateway settings.

## Local setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run from the repository root:

```bash
cd 01
uv python install 3.12
cp .env.example .env
uv sync --locked
uv run --locked python -m marketplace_agent doctor
```

`.python-version` selects Python 3.12 for development; the package supports Python 3.12+.
The default `dev` dependency group includes pytest and Ruff. Commit `uv.lock` alongside
dependency changes; `.env` and `.venv` are ignored.

Configuration comes from environment variables, then `.env` in the current working
directory, then defaults. Run commands from `01/` to load that file. `.env` is optional:
all future service URLs and the model identifier default to `None` when omitted.
Provided URLs must be valid HTTP(S) URLs, even though no connections are attempted.
See [.env.example](.env.example) for supported values. Do not store secrets in tracked files.

## CLI usage

```bash
uv run --locked python -m marketplace_agent --help
uv run --locked python -m marketplace_agent version
uv run --locked python -m marketplace_agent doctor
uv run --locked python -m marketplace_agent serve
```

The installed entry point also supports `uv run --locked marketplace-agent doctor`.
`version` prints the application name and package version. `doctor` validates configuration,
Python, and installed package initialization without contacting future services.
`serve` runs a development-only health endpoint at `http://localhost:8080/health`.
It returns JSON with `status`, `application`, and `version`; unknown paths return HTTP 404.
Use Ctrl+C to stop. Configuration errors return exit code 2; runtime failures return 1.

```bash
curl --fail http://localhost:8080/health
```

## Docker deployment

With Docker Engine/Docker Desktop and Docker Compose v2.24+ available, run from `01/`:

```bash
cp .env.example .env  # First setup only; keep an existing local .env.
docker compose up -d --build
docker compose ps
curl --fail http://localhost:8080/health
docker compose exec app python -m marketplace_agent doctor
docker compose exec app python -c "import marketplace_agent; print(marketplace_agent.__version__)"
docker compose logs app
docker compose down
```

Compose also starts without `.env`, using safe application defaults. Only `app` runs.
It uses a non-root user, locked runtime dependencies, an HTTP healthcheck, and graceful
SIGTERM handling. The health port is published on host loopback only; change `APP_PORT`
in `.env` to select another port. Compose binds the server to `0.0.0.0` inside the
container so the published port works. No platform override is needed on Apple Silicon.
The same Dockerfile can later run a different Python module by overriding its command.
The runtime image contains neither uv nor development tools; execute Python directly.

## Tests and code quality

```bash
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Tests cover package initialization, configuration sources/validation, CLI behavior, and
HTTP startup/shutdown. They use only local processes and loopback HTTP; no LLM, MCP,
gateway, marketplace, or internet connection is needed after dependencies are installed.
See [development](docs/development.md) for packaging, formatting, and troubleshooting.

## Future implementation roadmap

1. **Stage 02 — Bazoš MCP:** implement the first FastMCP server, marketplace search,
   price filtering, location and radius filtering, listing details, structured results,
   and tests. Introduce shared domain contracts and a reusable provider where needed.
2. **Stage 03 — Sbazar MCP:** implement the second independent FastMCP server,
   reusing shared interfaces and domain models.
3. **Stage 04 — agentgateway:** add the gateway to Compose, connect both MCP servers,
   and configure the external local LLM proxy.
4. **Stage 05 — Python AI Agent:** add LLM integration, MCP tool discovery, tool calling,
   tool result handling, orchestration, and an interactive CLI.
5. **Stage 06 — Integration and finalization:** add end-to-end tests, final documentation,
   assignment compliance verification, and a demonstration scenario showing the complete
   tool-call cycle.
