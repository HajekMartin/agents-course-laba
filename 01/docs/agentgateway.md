# Stage 04: agentgateway and local Unsloth Studio

agentgateway provides one MCP connection for both existing marketplaces and a separate
OpenAI-compatible connection for the local model. It performs protocol routing only.
Stage 05 adds the [Python AI agent](agent.md) on top of these unchanged routes.

## Distribution and configuration

Compose uses the official standalone image
`cr.agentgateway.dev/agentgateway:v1.7.0`, pinned to multi-platform manifest digest
`sha256:60216aafb03d37f94e952ff3d51d2f630a65b10ecaebdc0a864882f92610c45b`.
The manifest includes ARM64 and AMD64; Linux ARM64 was executed on Apple Silicon.
The gateway is not built from source.

[`config/agentgateway.yaml`](../config/agentgateway.yaml) is the complete native config,
mounted read-only. `config.storage.mode: readOnly` prevents UI edits; no database is
configured. Both MCP transports are stateless, with session encryption explicitly
disabled because no persistent sessions are used. Nothing must be configured in the UI.

The pinned version expands `${VARIABLE}` in file configuration. LLM `params.apiKey`
supports the secret reference `$UNSLOTH_API_KEY`. Compose explicitly passes all four
upstream variables; the mounted YAML is interpreted by agentgateway, not by Compose.
No templating script or proxy service is involved. Empty API keys are supported;
authenticated Unsloth requires a valid key.

The custom provider declares only `completions`. `params.baseUrl` includes the upstream
API prefix (usually `/v1`); the gateway appends `/chat/completions`. The exact incoming
model name is `${UNSLOTH_MODEL}` and is forwarded unchanged. Unknown models are rejected;
there is no wildcard, model alias, generation override, or cloud fallback.
`LLM_TIMEOUT` controls native request, backend, and response-idle timeouts in seconds.

## Ports and endpoints

These endpoints were exercised with v1.7.0:

| Endpoint | Purpose |
| --- | --- |
| `http://localhost:3000/mcp` | Unified Streamable HTTP MCP; initialize, tools/list, tools/call |
| `http://localhost:3001/v1/chat/completions` | OpenAI-compatible LLM chat completion |
| `http://localhost:3001/v1/models` | Gateway's configured model catalog, not upstream readiness |
| `http://localhost:3002/ui/` | Read-only gateway UI, on a separate gateway listener |
| `http://agentgateway:15021/healthz/ready` | Native gateway readiness, internal to Docker |
| `http://bazos-mcp:8001/mcp` | Existing Bazoš upstream, internal to Docker |
| `http://sbazar-mcp:8002/mcp` | Existing Sbazar upstream, internal to Docker |

The documented admin socket remains on container loopback at port **15000**; it is not
published. The supported UI gateway listener above makes the UI accessible without
exposing administrative shutdown/config-dump endpoints. Host gateway ports are
configurable; internal listeners remain 3000/3001/3002. Every published port binds to
`127.0.0.1`. Neither marketplace upstream is published.

Compose restarts the gateway when either MCP dependency is recreated (`depends_on.restart`).
This refreshes upstream connections/DNS: an already running v1.7.0 gateway was observed
returning MCP HTTP 500/connection refused after Python-service rebuilds changed their
container IPs. This is lifecycle handling within the existing four services.

The MCP endpoint exchanges JSON-RPC protocol messages and tool results. The LLM endpoint
accepts messages and generation parameters and returns an assistant completion. Sending
a chat-completion body to `/mcp` does not invoke an AI agent.

## MCP federation and names

The `bazos` and `sbazar` targets use Docker service discovery on the existing default
Compose network, with the internal URLs above. Both retain their original
`search_listings` tool. `prefixMode: always` produces the actual discovered names:

- `bazos_search_listings`
- `sbazar_search_listings`

Discovery and invocation verified these names and preservation of the original input
and output schemas. No underlying tools, filters, sorting, or parsing were changed.
`failureMode: failOpen` skips an unavailable target; the healthy target keeps its prefix
even when it is the only remaining server. All targets failing still causes an error.
Diagnostics treat missing tools as failures, not a complete federation.

## Environment and startup

Run from `01/`. Retain an existing `.env`; copy `.env.example` only for initial setup.
The file is ignored by Git and excluded from Docker builds.

```dotenv
GATEWAY_MCP_PORT=3000
GATEWAY_LLM_PORT=3001
GATEWAY_UI_PORT=3002
UNSLOTH_BASE_URL=http://host.docker.internal:8888/v1
UNSLOTH_MODEL=your-loaded-model-id
UNSLOTH_API_KEY=
LLM_TIMEOUT=120
```

Use the actual Unsloth API port, a loaded model ID, and its API key. Port 8888 is an
example/default, not a discovery assumption. Existing `AGENTGATEWAY_URL` and
`LLM_BASE_URL` point the web agent to gateway MCP and LLM listeners inside
Compose; Compose supplies those internal addresses. The Stage 01 `LLM_MODEL` field is
retained for compatibility but Stage 04 uses only `UNSLOTH_MODEL`.

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose run --rm --no-deps agentgateway --file /etc/agentgateway/config.yaml --validate-only
```

The MCP services and gateway can start without `.env`: MCP is usable, and the LLM route
uses the sentinel model name `model-not-configured` until actual settings are supplied.
The web app requires a configured model ID and reports missing model configuration on startup.
No Unsloth download, installation, model load, or server startup is performed.
Changes to Compose environment variables require container recreation:

```bash
docker compose up -d --force-recreate app agentgateway
```

All four services restart unless stopped. Initial gateway startup waits for both MCP
discovery healthchecks; there is no LLM startup dependency or inference healthcheck.
At runtime, unavailable MCP targets are handled independently. The official gateway
image contains no shell, Python, or curl: its Docker healthcheck runs native config
validation. A Docker `healthy` status alone does not prove traffic works; use the
explicit native readiness and integration tests below. Readiness does not imply
that Unsloth or a marketplace is available.

## Unsloth and Docker networking

Unsloth stays on the Mac, outside Compose. Container `localhost` refers to that container;
`host.docker.internal` is Docker Desktop's host address. A successful host curl does not
prove container reachability. The app uses that same Docker network.
During verification, direct API discovery and inference were also executed from a
temporary Python container sharing the gateway's exact network namespace.

First use the existing listener and verify it. If Docker cannot reach a loopback-only
listener, inspect its bind address, Docker Desktop networking, VPN and firewall rules.
Unsloth documents `-H` / `-p` options for selecting its bind address and port. An operator
can restart the existing Studio with `unsloth studio -H <bind-address> -p <actual-port>`;
this repository never runs that command. Prefer a dedicated reachable host interface
when available. `0.0.0.0` also opens LAN interfaces: require Unsloth API authentication
and a host firewall rule allowing Docker Desktop's backend while blocking unwanted LAN
clients. Keep router forwarding/tunnels off. Do not broaden the listener automatically.
See the official networking and Unsloth references below.

In Unsloth, create/manage credentials in **Settings → API** and put the key in the local
`.env`. Requests use Bearer authentication when configured. Model listing may include
unloaded variants; use an entry with `loaded: true`. Diagnostics do not select or load
another model. Gateway `/v1/models` reflects configuration, not upstream readiness.
Use the existing Studio model listing to select a loaded ID; the app never loads a model.

Copy the selected ID into `UNSLOTH_MODEL`, then recreate `app` and `agentgateway` as above.
For the live verification on 2026-11-07, upstream `/v1/models` reported
`unsloth/Qwen3.5-9B-GGUF` loaded (Q5_K_M). Direct and proxied requests both returned
HTTP 200, that model identity, and an assistant completion. The actual model ID is
stored only in local configuration, not hardcoded in the gateway or application.

## Protocol verification

The web UI shows the agent's actual tool requests/results. Gateway traffic is visible with:

```bash
docker compose logs --tail 50 agentgateway
```

The existing integration tests initialize/discover/call both MCP tools through the gateway,
validate their contracts, and verify direct/proxied fixture LLM routing. The internal
`gateway_check.py` module retains reusable contract/integration helpers, with no CLI.
Default source permissions return empty listings with their disabled-access warnings;
this verifies transport/failure semantics, not populated live marketplace search.

Successful plain chat transport does not establish native tool-calling compatibility.
The [agent live test](agent.md) exercises the complete smolagents cycle with the actual
configured model. No diagnostic installs, selects or downloads a model.

## Automated tests

```bash
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
GATEWAY_DOCKER_TESTS=true uv run --locked pytest tests/integration/test_agentgateway.py
```

Default tests require no LLM or Docker. The opt-in Docker tests build the existing Python
image, start fixture HTTP backends with the original two FastMCP servers on an isolated
temporary network, and run the pinned official gateway with the committed configuration.
No test calls a live marketplace or Unsloth. Tests remove their containers/network and
leave the user's Compose deployment running. Test backends are not Compose services.
Native `--validate-only` accepts the real configuration and rejects an invented property.
Protocol tests cover schemas, duplicate names, both populated search results, authenticated
mock LLM routing, message/generation preservation, wrong model rejection, timeouts, and
independent unavailable LLM/MCP behavior. A separate route verifies an unauthenticated
upstream and a custom API base path, including omission of the Authorization header.

An optional live test uses the existing `.env` key/model and requires reachable host URLs:

```bash
UNSLOTH_LIVE_SMOKE=true \
UNSLOTH_BASE_URL=http://127.0.0.1:8888/v1 \
LLM_BASE_URL=http://127.0.0.1:3001/v1 \
uv run --locked pytest tests/integration/test_agentgateway.py -k optional_live_unsloth
```

Substitute actual ports when different. No exact model wording or tool calling is tested.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Docker cannot bind a gateway port | Change the corresponding `GATEWAY_*_PORT`, recreate the gateway, and use the new host URL. |
| Gateway configuration is rejected | Run native `--validate-only`; check the pinned schema, all four upstream environment variables, and a numeric positive timeout. |
| Gateway is waiting during initial Compose startup | Check both MCP healthchecks with `docker compose ps` and their logs. |
| One search tool is missing | Inspect source container health/logs and Docker service names; rerun gateway integration checks. |
| Empty listings with a warning | Existing source restrictions remain in force. See the Bazoš/Sbazar documents; do not bypass them. |
| Unsloth discovery fails | Verify actual API port, `host.docker.internal`, listener binding, VPN/firewall and API key. Host-only success is insufficient. |
| LLM HTTP 401 | Correct `UNSLOTH_API_KEY` and recreate gateway/app. No key is required on the local gateway listener itself. |
| LLM HTTP 404 | Use the exact loaded ID from upstream `/v1/models`; check that the API base path includes `/v1` once. |
| LLM HTTP 503 | The configured local upstream cannot be reached. MCP remains independent; no cloud model is used. |
| LLM HTTP 504 | The configured timeout expired; check model responsiveness and adjust `LLM_TIMEOUT` if appropriate. |
| Docker says healthy but requests fail | The gateway Docker check validates config; run the integration tests to verify traffic. |
| Changes to `.env` have no effect | Recreate containers; restarting alone does not apply Compose environment changes. |

Use `docker compose logs --tail 100 agentgateway` for structured system/access logs,
including route, status, latency and model identity. Request bodies and credentials are
not added to logs by this configuration. Stop the infrastructure with `docker compose down`.

## Official references consulted

- [v1.7.0 release and artifacts](https://github.com/agentgateway/agentgateway/releases/tag/v1.7.0)
- [Standalone Docker deployment](https://agentgateway.dev/docs/standalone/latest/documentation/setup/install/docker/)
- [MCP federation modes](https://agentgateway.dev/docs/standalone/latest/documentation/mcp/configuration-modes/)
- [Streamable HTTP](https://agentgateway.dev/docs/standalone/latest/integrations/mcp/servers/http/)
- [Custom OpenAI-compatible providers](https://agentgateway.dev/docs/standalone/latest/integrations/llm/providers/custom/)
- [Model discovery/routing](https://agentgateway.dev/docs/standalone/latest/documentation/llm/api-types/models/)
- [Listeners](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/listeners/)
- [Storage and file environment substitution](https://agentgateway.dev/docs/standalone/latest/documentation/setup/storage/)
- [Timeouts](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/resiliency/timeouts/)
- [Logging](https://agentgateway.dev/docs/standalone/latest/documentation/observability/access-logs/view/)
- [Versioned schema validation](https://agentgateway.dev/docs/standalone/latest/reference/configuration/validation/)
- [Unsloth API, authentication and model listing](https://unsloth.ai/docs/basics/api)
- [Unsloth Studio host/port options](https://unsloth.ai/docs/get-started/install/mac)
- [Docker Desktop networking and firewall behavior](https://docs.docker.com/desktop/features/networking/)
