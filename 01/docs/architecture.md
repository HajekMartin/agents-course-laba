# Architecture

## Current implementation: Stages 01–04

One installable Python package contains the existing configuration/diagnostics CLI and
health server plus independent Bazoš and Sbazar FastMCP services. `app`, `bazos-mcp`, and
`sbazar-mcp` share the existing multi-stage Dockerfile and locked Python dependencies.
All run as UID 10001
with Compose init and graceful termination. Only the health port is published on host
loopback along with gateway ports 3000, 3001 and 3002. Upstream MCP is internal at
`http://bazos-mcp:8001/mcp` and
`http://sbazar-mcp:8002/mcp`. MCP healthchecks use actual tool discovery.

The module entry point and console entry point still call `cli.main`. Pydantic Settings
validates environment variables and optional `.env`; help/version work with invalid
configuration. Package metadata supplies the version. `health.py` uses only the standard
library and handles SIGINT/SIGTERM; `/health` reports process responsiveness without
probing external services. CLI diagnostics remain independent of MCP and marketplace access.

| Module | Responsibility |
| --- | --- |
| `cli.py`, `config.py`, `health.py` | Stage 01 diagnostics, settings, health lifecycle |
| `domain/models.py` | Shared `SearchRequest` and `Listing` Pydantic models |
| `providers/bazos.py` | Independent HTTP integration, URL/card parsing, filters/sorting |
| `providers/sbazar.py` | Independent JSON adapter, access checks, unsupported-geography warning |
| `providers/common.py` | Existing Bazoš robots and price filter/sort helpers reused by both providers |
| `mcp/bazos_server.py` | Exactly one `search_listings` tool, Streamable HTTP on 8001 `/mcp` |
| `mcp/sbazar_server.py` | The equivalent single-tool schema, Streamable HTTP on 8002 `/mcp` |
| `mcp/healthcheck.py` | Readiness through MCP discovery, without marketplace requests |
| `config/agentgateway.yaml` | Read-only native gateway config; two MCP targets and one local LLM model |
| `gateway_check.py` | Explicit readiness, MCP discovery/invocation and direct/proxied LLM diagnostics |

The fourth Compose service is the official agentgateway v1.7.0 Docker image, pinned by
version and manifest digest, with native ARM64 verified on Docker Desktop. It uses the
existing default network and service discovery. MCP federation is stateless, always
prefixes tools by target name, and skips unavailable targets (`failOpen`); missing targets
remain visible as failures in diagnostics. No marketplace tools or providers are modified.

```mermaid
flowchart LR
    Client[Protocol clients / diagnostics] -->|MCP :3000/mcp| Gateway[agentgateway container]
    Client -->|Chat completions :3001/v1/chat/completions| Gateway
    Gateway -->|Streamable HTTP :8001/mcp| BazosMCP[Bazoš FastMCP]
    Gateway -->|Streamable HTTP :8002/mcp| SbazarMCP[Sbazar FastMCP]
    Gateway -->|host.docker.internal / actual API port| Unsloth[Unsloth Studio on macOS]
    BazosMCP --> BazosProvider[Bazoš provider]
    SbazarMCP --> SbazarProvider[Sbazar provider]
```

The LLM listener serves only the exact `UNSLOTH_MODEL` name. A custom provider advertises
Chat Completions and forwards to `UNSLOTH_BASE_URL` with an optional environment-sourced
Bearer token. Native timeouts use `LLM_TIMEOUT` seconds. MCP has no LLM dependency.
The separate read-only UI listener is port 3002; the admin socket stays on container
loopback at 15000 and native readiness is internal at 15021. No database is configured.
See [gateway operations and verification](agentgateway.md).

The provider accepts a validated request and optionally an httpx client, which makes
HTTP behavior testable without FastMCP or network access. It checks operator permission
and robots before fetching one global search page. A 15-second timeout bounds requests;
there are no retries, caching, detail-page requests, geocoding, or ranking infrastructure.
Only listing summaries are parsed. Price bounds are rechecked locally. Relevance keeps
source order; price sorting precedes the result limit. Geographic responses warn about
unverifiable exact distances and reject unconfirmed postcode/radius form values.

Sbazar uses the same `SearchRequest`, `Listing`, inclusive price filtering and stable
sorting before the final limit. Its source-specific adapter requests one JSON page of
up to 60 summaries from the reference endpoint. Missing descriptions are nullable in
the shared listing model; Bazoš retains its established empty-string behavior.
Sbazar locality/strict radius cannot be verified and return empty listings with a
warning before HTTP; no additional geographic system is introduced.

Live searches on both sources are currently restricted by policy and default to
disabled. Sbazar's reference endpoint and live filter behavior remain unverified.
See [Bazoš MCP](bazos-mcp.md) and [Sbazar MCP](sbazar-mcp.md). An empty result with a
warning differs from a successful empty search. Tests use fixture HTML/JSON, httpx
mocks, and MCP clients/ASGI transport, including equality of both tool schemas.

## Planned system

The complete system remains the original roadmap. Both MCP/provider modules and the
Stage 01 CLI/health foundation and Stage 04 gateway integration are implemented. The
diagram below describes the future system, including the unimplemented Python agent:

```mermaid
flowchart TD
    User[User] --> Agent[Python Agent]
    Agent --> Gateway[agentgateway]
    Gateway --> LLM[Local OpenAI-compatible LLM]
    Gateway --> MCPGateway[MCP Gateway]
    MCPGateway --> BazosMCP[Bazoš FastMCP Server]
    MCPGateway --> SbazarMCP[Sbazar FastMCP Server]
    BazosMCP --> BazosProvider[Bazoš Provider]
    SbazarMCP --> SbazarProvider[Sbazar Provider]
    BazosProvider --> Bazos[Bazoš Marketplace]
    SbazarProvider --> Sbazar[Sbazar Marketplace]
```

The MCP Gateway node is agentgateway routing, not an additional deployment. Stage 04 adds
agentgateway, routing, and a proxy to an externally hosted OpenAI-compatible model.
Stage 05 will implement Python user interaction and the LLM/tool loop; Stage 06 will
verify the complete flow. Python AI agent behavior and LLM tool calling do not exist yet.

Providers must stay independent of MCP and the future agent. Add shared services only
when concrete reuse warrants them; avoid speculative contracts and base classes.
`MARKETPLACE_MODE` remains reserved. Optional service URLs are syntax-checked but are
never probed by diagnostics. Each marketplace permission flag controls only its source
access; neither bypasses robots restrictions or affects MCP readiness.
