# Stage 01 verification

Verified on **2026-11-08** on macOS arm64 with Docker Desktop 4.41.2, Docker Engine
28.1.1 and Compose v2.35.1. The main project was left running on port 5678.
No owner account, workflow, finance table, financial record, model, or MCP token
was created by these checks.

## Passed

| Check | Actual evidence |
| --- | --- |
| Official version pins | Pulled `docker.n8n.io/n8nio/n8n:2.46.6` and `postgres:17.11-bookworm`; running n8n reports `2.46.6`, PostgreSQL reports `17.11` |
| Compose validation | `docker compose config --quiet` succeeds; parsed interpolated config confirms expected credentials, URLs, timezone, volumes, two services and loopback binding without printing secrets |
| Secret guard | Configuration with `.env.example` fails because mandatory secrets are empty |
| Clean initialization | A separate disposable Compose project using empty volumes completed SQL initialization and reached healthy status for both services; its finance database had zero user tables |
| Configuration validation | Conflicting database names and invalid SQL identifiers fail with nonzero psql exit codes before creation statements |
| Runtime readiness | Both main services are `healthy`; host GET `/healthz/readiness` returns HTTP 200 and `{"status":"ok"}` |
| Editor access | Host GET `http://localhost:5678/` returns HTTP 200; the instance reports initial owner setup is still required |
| Database backend | Official n8n migrations exist in the `n8n` PostgreSQL database; no `/home/node/.n8n/database.sqlite` exists |
| Database isolation | Both application roles are non-superusers without `CREATEDB`/`CREATEROLE`; neither has CONNECT to the other application database; a real n8n-role TCP connection to finance is rejected |
| Finance readiness | Real TCP login as `finance_app` succeeds and reports database `finance`, schema `finance`; zero user tables |
| Port exposure | n8n publishes `127.0.0.1:5678`; PostgreSQL has no published host port |
| Persistence | Both containers were force-recreated; a temporary nonfinancial marker in the n8n volume survived, and both application database OIDs stayed identical; the marker was then removed |
| Encryption/configuration | Persistent n8n config key matches the configured environment value; config mode is 0600; values were not printed |
| Built-in MCP presence | The pinned image contains the instance MCP controller and implementations for create/update/validate/test/execute/result inspection; its runtime configuration enables the MCP workflow builder by default |
| MCP endpoint identity | The selected image defines `/mcp-server/http`; the live unauthenticated POST returns HTTP 404 with `{"message":"MCP access is disabled"}` before owner activation, rather than exposing tools |
| Codex command support | Installed `codex-cli 0.164.0-alpha.11.1` help confirms `mcp add --url`, `mcp login`, and `--bearer-token-env-var`; commands were also checked against official OpenAI/n8n documentation |
| Git boundaries | `.env` is ignored; tracked Assignment 01 contents and index entries are unchanged; all project source additions are in `02/` |
| Stage boundary | PostgreSQL reports zero workflows and zero financial user tables; `workflows/` contains documentation only |

The clean initialization check used project name `finance-assistant-02-bootstrap-check`
and loopback host port 15678. Only its temporary containers, network, and volumes
were removed afterward. The main project's persistent volumes remain intact.

## Incomplete external/manual checks

| Check | Observed result / next action |
| --- | --- |
| Authenticated Codex MCP request | **Not performed.** Complete the owner account, enable instance MCP, register Codex and approve OAuth in the browser. Then inspect live tools and execute `search_workflows`. Static tool presence and HTTP probes do not prove authenticated connectivity. |
| Unsloth models-list request | **Attempted from the n8n container; HTTP 401.** The sample configured endpoint `http://host.docker.internal:8888/v1/models` responded but did not authorize the request. Set the actual Studio API URL, exact model ID and any required private key in `.env`, recreate n8n and rerun the check. No successful model-list or inference claim is made. |
| Inference and tool calling | **Not tested.** Stage 01 only provides a read-only models-list procedure and does not implement inference workflows. |
| Windows/Linux runtime | Configuration includes host-gateway support and documentation; live checks were performed only on macOS. Native Linux may need a Docker-facing host model listener and firewall configuration. |

The user must complete these authentication/configuration steps; this repository
contains no automated browser authentication or committed MCP credentials.

## Remaining implementation limits

- Instance MCP remains disabled until the owner explicitly enables it. Creating,
  editing, executing and inspecting workflows are additionally subject to granted
  scopes and workflow access. No claim of an authenticated MCP session is made.
- Only two containers are deployed. Python Code nodes are disabled; the image's
  default internal JavaScript task runner is used. The stock image still logs an
  unavailable internal Python runner and an internal-runner deprecation notice;
  neither blocks readiness. An isolated external runner would need a deliberate future
  architecture change and is outside this stage.
- The bridge provides host connectivity, not an outbound destination allowlist.
  Keep all future inference on the configured local LLM and use synthetic data
  when developing with Codex.
- Owner creation, n8n workflow credentials and financial schema migrations are
  intentionally manual or deferred to later stages as described in the guides.
