# Development

## Python and uv

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) using the instructions
for your operating system. Python 3.12 is the development and Docker baseline; packaging
supports Python 3.12 and newer. uv can install Python without a separate system setup:

```bash
cd 01
uv python install 3.12
cp .env.example .env
uv sync --locked
```

Run `cp` only during first setup; retain existing local configuration. `.env` is optional,
is ignored by Git, and is excluded from Docker builds. Never add credentials to tracked
files. The example contains placeholder addresses; only Bazoš MCP currently runs as a service.

`uv sync --locked` creates `.venv`, installs the project in editable mode using its
`src` layout, and installs the default development group. No `PYTHONPATH` workaround is
needed. `uv.lock` is the dependency source for reproducible installations. The small
runtime dependencies are Pydantic, Pydantic Settings, FastMCP, httpx, and BeautifulSoup.
pytest and Ruff are development dependencies; async tests use `asyncio.run` without
an additional test plugin.

## Configuration

Pydantic Settings loads environment variables before `.env` values and defaults. `.env`
is resolved relative to the current working directory, so run commands from `01/`.
Unknown `.env` keys are ignored to allow later Compose settings without breaking the app.
Do not use blank values for optional URLs: omit those keys instead.

| Variable | Default without `.env` | Accepted values / purpose |
| --- | --- | --- |
| `APP_ENV` | `development` | `development`, `test`, `production` |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `MARKETPLACE_MODE` | `demo` | `demo`, `live`; both reserved for the future agent |
| `BAZOS_ACCESS_PERMITTED` | Unset (disabled) | Exact `true` enables source access only with operator permission; robots is still enforced |
| `APP_HOST` | `0.0.0.0` | Health server bind hostname/address; IPv4 binding |
| `APP_PORT` | `8080` | Integer from 1 through 65535 |
| `LLM_BASE_URL` | Unset (`None`) | Optional HTTP(S) URL |
| `LLM_MODEL` | Unset (`None`) | Optional nonempty model identifier |
| `AGENTGATEWAY_URL` | Unset (`None`) | Optional HTTP(S) URL |
| `BAZOS_MCP_URL` | Unset (`None`) | Optional HTTP(S) URL |
| `SBAZAR_MCP_URL` | Unset (`None`) | Optional HTTP(S) URL |

URLs are checked for syntax only; CLI diagnostics never require those services.
Invalid configuration produces a concise error with exit code 2 without
printing supplied values. Version and help remain available for diagnosis.

## CLI and health server

```bash
uv run --locked python -m marketplace_agent --help
uv run --locked python -m marketplace_agent version
uv run --locked python -m marketplace_agent doctor
uv run --locked marketplace-agent doctor
uv run --locked python -m marketplace_agent serve
```

`doctor` checks the loaded configuration, Python 3.12+, and package initialization.
It does not perform network requests. `serve` is a lightweight development diagnostics
process, not an API for marketplace search. From another terminal:

```bash
curl --fail http://localhost:8080/health
```

Expect JSON containing `status: "ok"`, the application name, and package version.
Other paths return 404. Stop with Ctrl+C or SIGTERM; a clean shutdown returns code 0.
For local-only binding outside Docker, set `APP_HOST=127.0.0.1` in `.env`.

## Docker

Use Docker Desktop on macOS/Windows or Docker Engine on Linux, with Compose v2.24+.
Native ARM64 (Apple Silicon) and AMD64 images are selected automatically.

```bash
docker compose config --quiet
docker compose up -d --build --wait
docker compose ps
docker compose exec app python -m marketplace_agent version
docker compose exec app python -m marketplace_agent doctor
docker compose exec app python -c "import sys; print(sys.version)"
docker compose logs -f app
docker compose down
```

The services are `app` and `bazos-mcp`, sharing the existing Dockerfile.
It builds a non-editable installation with
`uv sync --locked --no-dev --no-editable`, then copies the virtual environment into a
non-root runtime image. Its Python command handles termination signals; Compose uses an
init process and a five-second stop grace period. The healthcheck requests the real HTTP
endpoint, verifies its JSON status, and requires no curl or host Python installation.

Compose loads optional `.env` values. `APP_PORT` controls both the internal listening port
and the port published on host `127.0.0.1`. Compose sets internal `APP_HOST=0.0.0.0` so port
forwarding works regardless of local bind preferences. Bazoš MCP listens internally on
`http://bazos-mcp:8001/mcp`, with no published host port. LLM, Sbazar, and gateway
hostnames remain future configuration. See [Bazoš MCP](bazos-mcp.md) for calls and source restrictions.

Source files are packaged into the image; rebuild after changes. Override the command to
reuse the image for the Bazoš MCP module. Python dependencies are locked, and
the uv image has an explicit version. The Python base tag still receives upstream
patches; strict bit-for-bit image reproduction would also require pinning image digests.
No secret `.env` file or development tools are included in the runtime image.

The build follows the official [uv Docker guidance](https://docs.astral.sh/uv/guides/integration/docker/).
Optional `env_file` handling is documented in the
[Compose service reference](https://docs.docker.com/reference/compose-file/services/#env_file).

## Tests, linting, formatting, and packaging

```bash
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked ruff format .
uv build
```

Tests isolate environment values and `.env` files in temporary directories. Startup tests
launch a child Python process, use loopback HTTP, and verify graceful termination for
SIGINT and SIGTERM. Bazoš tests use fixture HTML, mocked HTTP, and local MCP/ASGI
transports. The default suite needs no external network, marketplace, LLM, or gateway.
The [optional live smoke test](bazos-mcp.md#testing) requires explicit permission and opt-in.
Dependency installation and image builds require package/image downloads on a cold cache.

Builds produce a wheel and source archive in ignored `dist/`. To use another supported
Python version without changing `.python-version`, run `uv run --python 3.13 --locked pytest`.

## Dependency and module changes

```bash
uv add package-name
uv add --dev development-package
uv lock --check
uv sync --locked
```

Review `pyproject.toml` and `uv.lock` together. Add libraries only for implemented behavior.
Use `uv lock --upgrade` only for deliberate dependency
updates. The build backend is declared separately under `[build-system]`.

Add modules under `src/marketplace_agent/` when they implement real behavior. Introduce
new modules only as needed. The existing `domain`, `providers`, and `mcp` packages
implement Stage 02. Keep providers independent of MCP and pass dependencies explicitly. Add shared
services only when behavior is reused. Update documentation as capabilities become real.
See [architecture.md](architecture.md) for the planned boundaries.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `uv: command not found` | Install uv and reopen the shell or add its installation directory to `PATH`. |
| Python 3.12 is unavailable | Run `uv python install 3.12`; check outbound access if downloads fail. |
| `ModuleNotFoundError` / missing distribution metadata | Run `uv sync --locked` in `01/` and use `uv run`; the src layout requires installation. |
| `.env` settings are ignored | Check the working directory and environment variables, which override `.env`. |
| `Invalid application configuration` | Match supported enum values and port range; omit unused URLs instead of leaving them blank. |
| Lockfile is outdated | After intentional metadata/dependency changes run `uv lock`, review it, then `uv sync --locked`. |
| `Address already in use` | Stop the other health server or change `APP_PORT`, then recreate the container. |
| Cannot connect to Docker daemon | Start Docker Desktop/Engine and verify `docker info`. |
| Compose rejects optional `env_file` | Upgrade to Compose v2.24+ (check `docker compose version`). |
| Container is unhealthy | Inspect `docker compose logs app` and `docker compose exec app python -m marketplace_agent doctor`. |
| Code changes do not appear in Docker | Rebuild with `docker compose up -d --build`. |
| uv cache is not writable | Set `UV_CACHE_DIR` to a writable directory for that environment. |

Missing future LLM, Sbazar MCP, and gateway services never prevent CLI diagnostics.
Bazoš source access restrictions return tool warnings and do not prevent MCP startup.
The MCP module reads its permission flag directly from the environment; it does not
load `.env` on local runs. Compose injects the optional `.env` into both containers.
