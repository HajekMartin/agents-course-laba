# Development

## VS Code: one launch button

Open the repository root (the folder containing `01/` and `.vscode/`). Keep Docker Desktop
running and the external Unsloth API/model loaded. Preserve your existing `01/.env`.
On first setup only, copy `.env.example` and configure the actual model ID/base URL/key.

Choose **Run and Debug → Marketplace: Start Web UI → ▶ / F5**. The launch profile:

1. Runs `docker compose up -d --build --wait` from `01/`.
2. Opens the standard smolagents GradioUI at `http://localhost:8080` in Chrome.
3. Runs `docker compose stop` when the debug session stops.

This uses VS Code's built-in Chrome browser debugger, not a Python debug attachment inside
the container. If `APP_PORT` changes, update `.vscode/launch.json`. No Node/pnpm/frontend
setup or custom launch script is needed. The model is not installed or loaded by this task.

**Terminal → Run Task** also offers **Marketplace: Start**, **Marketplace: Stop**, and
**Marketplace: Tests**. The test task requires uv locally; the Docker UI launch does not.

## Docker

```bash
cd 01
docker compose up -d --build --wait
docker compose ps
docker compose logs -f app
docker compose logs --tail 50 agentgateway
docker compose stop
```

The app healthcheck requests `/` on the configured app port. This establishes UI readiness,
not live model/marketplace access. MCP checks use actual discovery. The gateway Docker
check validates configuration; integration tests verify actual traffic.

## Local Python and quality checks

```bash
cd 01
uv sync --locked
LLM_BASE_URL=http://127.0.0.1:3001/v1 \
AGENTGATEWAY_URL=http://127.0.0.1:3000/mcp \
APP_HOST=127.0.0.1 APP_PORT=8081 uv run --locked python -m marketplace_agent
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
```

`python -m marketplace_agent` starts only the web UI. Gradio supplies the interface and
agent-step view; **New chat** resets memory. There is no interactive command-line mode.
Settings load environment variables over `.env` (relative to the current directory) and
defaults. Unknown `.env` keys are ignored. Empty optional URLs are invalid. App/model/tool
limits are listed in [agent configuration](agent.md#configuration).

Default tests use a fake model with the real smolagents loop, fake MCP results and provider
fixtures. Optional [Docker gateway tests](agentgateway.md#automated-tests) use isolated
fixture backends. Actual Unsloth verification is an explicit opt-in:

```bash
AGENT_LIVE_E2E=true \
LLM_BASE_URL=http://127.0.0.1:3001/v1 AGENTGATEWAY_URL=http://127.0.0.1:3000/mcp \
uv run --locked pytest tests/integration/test_agent_live.py -s
```

No test failure is hidden by hardcoded search results. Source restrictions stay enforced.
