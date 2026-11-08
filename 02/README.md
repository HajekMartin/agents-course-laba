# AI Finance Assistant — Assignment 02, Stage 01

Local infrastructure for a future no-code Finance Assistant built with **n8n**.
Stage 01 implements Docker Compose, PostgreSQL isolation and persistence, local
Unsloth connectivity checks, and instructions for developing workflows through
n8n's built-in instance-level MCP server. Assignment 01 in `../01/` is independent.

**No banking workflows, financial tables, imports, or AI agent are implemented.**
The final deliverables will be importable n8n workflow JSON files, including one
main workflow demonstrating the assignment.

## Original assignment

> Tvorba no-code agenta
>
> Navrhni a vytvoř agenta v libovolné “No code” platflormě, který pracuje s databází, používá nástroje a odpovídá na dotazy přes LLM.
>
> No code platformy:
> - N8N
> - LangFlow
>
> Formát: JSON soubor s definicí workflow pro N8N a LangFlow
>
> Deadline: 23. 11. 2026 23:59
>
> Maximální počet bodů: 100 bodů.

Selected platform: **n8n**.

## Planned features

Later stages will import bank statements from CSV/XLSX, store transactions,
prevent duplicate imports, categorize expenses, answer financial questions,
calculate spending by category, compare periods, identify recurring payments,
and retrieve transaction history. Development will use synthetic statements.

## Architecture

The host runs Codex, a browser, and the user's existing Unsloth Studio. Docker runs
two services on a dedicated bridge network. Only n8n publishes a port, on IPv4
loopback. Its built-in MCP endpoint and editor share this authenticated service.
PostgreSQL stores n8n internals and the empty finance database separately.
See the [architecture diagram and boundaries](docs/architecture.md).

## Technology stack

| Component | Pinned official image / location | Purpose |
| --- | --- | --- |
| n8n Community | `docker.n8n.io/n8nio/n8n:2.46.6` | Editor, runtime, built-in MCP |
| PostgreSQL 17 | `postgres:17.11-bookworm` | One server, two application databases |
| Docker Compose v2 | Host | Lifecycle, network, volumes, readiness |
| Unsloth Studio | Existing host installation | Future local OpenAI-compatible inference |
| Codex | Existing local CLI / IDE | Future workflow development over MCP |

n8n's official Docker guide identified `2.46.6` as stable when verified.
Creation/editing through instance MCP requires n8n **2.13.0 or later**; this pin
also includes the newer MCP connection settings. No license activation, community
packages, third-party MCP server, or additional assistant stack is required here.

Official references:
[n8n Docker](https://docs.n8n.io/hosting/installation/docker/),
[n8n Compose](https://docs.n8n.io/deploy/host-n8n/install-options/install-using-docker-compose),
[PostgreSQL image](https://hub.docker.com/_/postgres),
[instance MCP](https://docs.n8n.io/connect/connect-to-n8n-mcp-server),
[MCP client examples](https://docs.n8n.io/connect/connect-to-n8n-mcp-server/mcp-client-examples),
[Codex MCP](https://developers.openai.com/codex/mcp).

## Directory structure

```text
02/
├── README.md
├── compose.yaml
├── .env.example
├── .gitignore
├── config/
│   ├── create-env.mjs
│   └── verify-unsloth.mjs
├── database/
│   └── init/
│       └── 10-create-databases.sql
├── workflows/
│   └── README.md
└── docs/
    ├── architecture.md
    ├── development.md
    ├── codex-mcp.md
    └── verification.md
```

`workflows/README.md` reserves and explains the future deliverable location;
there are intentionally no placeholder workflow JSON files.

## Prerequisites

- Docker Desktop with its daemon running (macOS/Windows), or Docker Engine with
  Compose v2 (Linux). No host Python, Node.js, n8n, or PostgreSQL installation.
- A free local TCP port `5678`, Internet access for the initial official image pulls.
- A browser for initial owner setup and explicit OAuth consent.
- Local Codex CLI or IDE for MCP development; the CLI is not required to start Docker.
- Existing Unsloth Studio is optional for Stage 01 startup. No model is installed
  or started by this project.

Commands below use a POSIX shell; on Windows use WSL2 with Docker Desktop integration.

## Docker startup

From the repository root, generate a private `.env` with independent random database
passwords and an encryption key using Node **inside the official n8n image**:

```bash
cd 02
docker run --rm --entrypoint node \
  --mount "type=bind,src=$PWD,dst=/project" --workdir /project \
  docker.n8n.io/n8nio/n8n:2.46.6 config/create-env.mjs
docker compose config --quiet
docker compose up -d
```

The generator refuses to overwrite an existing `.env`. It does not print secrets.
Alternatively copy `.env.example` to `.env` and fill the four mandatory secrets
with separate strong random values. Compose rejects missing or empty secrets.
Keep the generated file and backups private; `.env` is ignored by Git.

Wait for readiness without fixed sleeps:

```bash
docker compose up -d --wait --wait-timeout 180
docker compose ps
```

Only the first startup needs environment generation. Subsequent starts are simply
`cd 02` followed by `docker compose up -d`.

In VS Code, open the repository root and select **Run and Debug → Finance: Start n8n → F5**.
The profile starts this project's services, waits for readiness, and opens Chrome
at `http://localhost:5678`. Ending the debug session stops only this project's
services and preserves their data. Generate `.env` once using the steps above
before the first launch. If you change `N8N_PORT`, update this profile's browser
URL in `.vscode/launch.json` accordingly. The Marketplace profile stays available.

### Environment configuration

| Variables | Requirement |
| --- | --- |
| `POSTGRES_PASSWORD`, `N8N_DB_PASSWORD`, `FINANCE_DB_PASSWORD` | Mandatory, separate random secrets |
| `N8N_ENCRYPTION_KEY` | Mandatory stable secret; preserve with backups |
| `POSTGRES_USER` | Bootstrap administrator, default `postgres`; never used by n8n |
| `N8N_DB_NAME`, `N8N_DB_USER` | Default `n8n` / `n8n` |
| `FINANCE_DB_NAME`, `FINANCE_DB_USER` | Default `finance` / `finance_app` |
| `N8N_HOST`, `N8N_PORT` | Default `localhost` / `5678`; host-side URL and port |
| `TIMEZONE` | Default `Europe/Prague`; container and n8n schedule timezone |
| `UNSLOTH_BASE_URL`, `UNSLOTH_MODEL` | Required only for checking/using the existing local LLM |
| `UNSLOTH_API_KEY` | Optional, only if the local API requires it |

Application role/database names must be distinct lowercase SQL identifiers (up to
63 characters) and must not reuse system database or administrator names.
Changing database names/passwords in `.env` after initialization does not migrate
existing storage. See [development and persistence](docs/development.md).
Container port `5678` stays fixed even when the host-side `N8N_PORT` changes.
Keep `N8N_HOST=localhost`; setting it does not change the loopback publishing boundary.

## n8n first-time setup

1. Open **http://localhost:5678** (use the configured host port if changed).
2. Complete the built-in setup form and create your own owner account with a strong
   password. The project never creates, bypasses, or disables this account.
3. Skip optional license registration and cloud/AI integrations. Community edition
   is sufficient for this infrastructure.
4. Enable MCP and authorize Codex using the instructions below.

The owner account is local to this n8n instance. Container health does not imply
owner setup or MCP authorization has been completed.

## PostgreSQL configuration

The `postgres` container has **no published host port**. Use `docker compose exec`
for inspection. On an empty volume the official entrypoint creates:

| Database | Owner / login | Contents in Stage 01 |
| --- | --- | --- |
| `postgres` | `POSTGRES_USER` | Bootstrap/administration |
| `n8n` | `N8N_DB_USER` | n8n's own tables/migrations in `public` |
| `finance` | `FINANCE_DB_USER` | Empty `finance` schema; no financial tables |

Each application role is a non-superuser without role/database creation rights.
Public database privileges are revoked so the two application roles cannot connect
to each other's database. Database owner privileges support future migrations;
a more restricted runtime role can be added with the future finance schema.
The future PostgreSQL n8n credential will use host `postgres`, port `5432`, database
`finance`, and the finance account from `.env`. It is **not created in Stage 01**.
The finance password is not passed to the n8n container.

Named volumes store PostgreSQL data at `/var/lib/postgresql/data` and n8n data at
`/home/node/.n8n`, including instance configuration even though SQLite is unused.

## Unsloth connectivity

In your existing Studio, inspect the API/server settings and the generated
OpenAI-compatible client example. Identify its API base URL (usually ending in
`/v1`, not necessarily the Studio web UI URL), configured API port, and optional key.
Use its model list endpoint (`<base URL>/models`) to obtain the exact model ID.

Configure **your actual values** in `.env`; these are examples:

```dotenv
UNSLOTH_BASE_URL=http://host.docker.internal:8888/v1
UNSLOTH_MODEL=your-model-id
UNSLOTH_API_KEY=
```

From a container, `localhost` means the container itself. Use
`host.docker.internal` for the host. Docker Desktop handles host routing on macOS
and Windows; the explicit `host-gateway` mapping also prepares Linux routing.
On native Linux a host listener bound only to `127.0.0.1` is not normally reachable
through the bridge gateway. Bind to the host's Docker-facing interface and restrict
access with the host firewall if necessary. On macOS, first try the existing local
listener through Docker Desktop. Do not enable public forwarding or open the API
to the LAN unnecessarily; a wildcard bind needs appropriate firewall restrictions.

Apply changes and make a real **GET /models** request from the n8n container:

```bash
docker compose up -d n8n
docker compose exec -T n8n node /opt/finance/verify-unsloth.mjs
```

The check prints available IDs and succeeds only when the configured model is
listed. It sends no prompt, performs no inference, rejects redirects, and times
out after 10 seconds. A models-list success does not establish tool-calling or
inference compatibility. No cloud fallback or automatic n8n AI credential exists.
Future workflows must explicitly use this local endpoint and model; environment
access inside workflow nodes stays blocked, so configure n8n credentials locally
when that stage is implemented.

## Codex MCP setup

1. Sign in as the owner. Open **Settings → Instance-level MCP → Enable MCP access**.
2. Select **Connect** in **Connection details**, choose **OAuth (recommended)**,
   and select **Codex**. Confirm the displayed Server URL is
   `http://localhost:5678/mcp-server/http`.
3. In a local terminal with Codex available:

   ```bash
   codex mcp add n8n --url "http://localhost:5678/mcp-server/http"
   codex mcp login n8n
   codex mcp list
   ```

4. Approve access in the n8n browser authorization screen, reviewing the requested
   read/build/execute permissions. This is an explicit manual consent step.
5. Start a new Codex session or restart the IDE extension; inspect `/mcp` and ask
   Codex to list the server's tools and run a read-only `search_workflows` request.

Server registration alone does not prove an authenticated connection. The detailed
[Codex MCP guide](docs/codex-mcp.md) covers permission checks, the official bearer-token
alternative, execution limits, and troubleshooting. No MCP tokens are generated
or stored by this project. No separate MCP server is installed.

## Verification commands

Run from `02/` after generating `.env`:

```bash
docker compose config --quiet
docker compose up -d --wait --wait-timeout 180
docker compose ps
curl --fail --silent --show-error http://localhost:5678/healthz/readiness
curl --fail --silent --show-error --output /dev/null http://localhost:5678/
docker compose exec -T postgres sh -c 'pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d postgres'
docker compose exec -T n8n n8n --version
docker compose exec -T n8n node /opt/finance/verify-unsloth.mjs
```

The last command requires a running, correctly configured Unsloth API. MCP verification
requires the owner setup and authorization above. See [recorded verification results](docs/verification.md)
and [database/persistence inspection](docs/development.md).

## Current implementation status

Implemented: two pinned official services, PostgreSQL-backed n8n, persistent volumes,
loopback editor publishing, database isolation and empty finance schema, readiness
dependencies, `Europe/Prague`, configurable host-model connectivity, and MCP setup
documentation. Authentication remains enabled. n8n diagnostics, update notifications,
templates, personalization, and community package installation are disabled.
Python Code nodes are disabled; this two-service stage uses the image's built-in
JavaScript runner and does not deploy an external task-runner service.

The bridge allows outbound connectivity to the host; it is not an egress firewall.
Do not configure cloud model credentials or send bank statements to cloud providers.
Codex is a development client whose provider may receive tool responses: use synthetic
data and keep real financial data out of workflow parameters, pin data, and executions
visible to development clients. No Docker socket or host home directory is mounted.

## Future stages

1. Define finance tables and safe synthetic test inputs.
2. Build CSV/XLSX import, normalization, categorization, and deduplication workflows.
3. Build the local-LLM Finance Assistant and its scoped database tools.
4. Validate/test through MCP, export workflows, and review sanitized JSON in Git.

The intended development cycle is documented in [development.md](docs/development.md).
Stage 01 stops before these workflow and agent features.
