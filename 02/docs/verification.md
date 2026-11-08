# Verification

## Anonymous local demo access — 2026-11-08

At the user's request, both published form/chat triggers now use Authentication =
None. Anonymous GET requests return HTTP 200 for both URLs, including requests
carrying stale incorrect Basic Auth headers. Actual anonymous CSV/XLSX uploads,
repeat uploads, invalid rows, missing columns and unsupported extensions passed.
A real anonymous chat POST also succeeded and invoked get_spending_summary,
returning October Housing 14000 CZK and total spending 24518.75 CZK.
The refreshed exports omit the unused Basic Auth references. Setup no longer
creates a separate web password/credential. The earlier authentication checks below
record the original configuration. The Docker port remains bound to localhost;
n8n editor and MCP authentication are unchanged.

## Stage 02 — 2026-11-08, Europe/Prague

Verified against the real existing n8n 2.46.6 and PostgreSQL 17.11 Docker services.
MCP OAuth was already enabled by the owner. Initial authenticated discovery returned
zero workflows and zero credentials. Both application workflows were then created
through MCP in the owner's personal project and published locally.

| Check | Actual result |
| --- | --- |
| Node compatibility | Live MCP search/type definitions and per-node validation: Form Trigger 2.1, Extract From File 1.2, Postgres/Tool 2.8, Chat Trigger 1.5, AI Agent 3.1, OpenAI Chat Model 1.3, Simple Memory 1.4, Code 2, IF 2.4, Respond to Webhook 1.5, Crypto 2 |
| Reproducible schema | Both SQL files applied; five finance tables and reporting view exist; reapplication succeeds |
| Money/constraints | `tests/database.sql` passed: NUMERIC(18,2), exact 0.10+0.20, Czech formatting, impossible dates, sign checks, FK failure, duplicates and reader privileges; test writes rolled back |
| First CSV | Actual multipart Form Trigger upload: processed 43, inserted 42, duplicate 1, invalid 0 |
| First XLSX | Actual multipart Form Trigger upload: processed 44, inserted 1, duplicate 43, invalid 0 |
| Repeat uploads | CSV skips 43 and XLSX skips 44; neither inserts another transaction |
| Invalid inputs | Invalid amount and impossible date reported with row numbers; missing columns rejected; unsupported extension rejected |
| Initial authentication (historical) | Basic Auth originally returned 401 without credentials; this was subsequently replaced with anonymous demo access at the user's request |
| Local inference | API key copied privately from Assignment 01 with user authorization; authenticated GET /models from n8n succeeds; model list also resolved via MCP load-options |
| Native tool calls | Real OpenAI-compatible completion returned finish_reason=tool_calls; genuine AI Agent invoked all four actual Postgres Tool nodes |
| Tool SQL | All four actual exported queries executed successfully under finance_reader; merchant Alza net 5000/refund 1000, total three-month income 135000, net balance 72903.75, average spending 20698.75, comparison 5780 / 30.85% |
| Required end-to-end question | Czech October question -> local LLM -> get_spending_summary -> Postgres category rows -> local LLM -> final Czech response; all eight category amounts equal independent SQL over transactions/categories |
| Required answer | Housing 14000.00 CZK; Shopping 5000.00; Groceries 2720.75; total net spending 24518.75 |
| Conversation | A successful same-session follow-up queried again and returned October Groceries 2720.75 CZK; conversation memory retained October |
| Last diagnostic suite | Six live questions exercised category summary, follow-up, income, monthly figures, largest transaction and comparison. All required tool-call/primary-amount assertions passed; synthetic raw tool evidence is in tests/acceptance-results.json |
| Evidence safety | Actual exported evidence-node code tested with real-looking outputs: supported values accepted; fabricated value, absent/failed tool results rejected; an unsupported number inside a range removed; retries bounded to two |
| Exports | Actual CLI exports sanitized to inactive JSON without pin/static execution data or secret values; credential references retained for reassignment |
| Project boundaries | Original assignment retained verbatim, Assignment 01 diff empty, .env ignored, no real statements or credentials in source artifacts |

The agent was tuned using synthetic data. Earlier runs sometimes skipped tools on
follow-ups, repeated text, invented an extra amount, or associated a known amount
with an incorrect month. The final workflow retries missed tool calls twice and
filters unsupported numeric sentences. It cannot formally verify the semantic
association of every label/date in free text. The six diagnostic assertions verify
actual tool calls and required amounts, not perfect accuracy of every sentence.
Read exact query results for consequential decisions. There is no cloud fallback
and no fake tool execution.

The final normal chat hides intermediate transaction traces. To rerun the full
synthetic diagnostic harness, set `exposeTestEvidence = true` in **Return Verified
Answer**, publish, run `node tests/chat.mjs`, then restore false and publish again.

Credentials were created with documented Server CLI import because MCP exposes no
credential creation. The supported Form Trigger 2.1 response-node mode avoids
persistent waiting execution state; changing its typeVersion required CLI roundtrip
because MCP cannot set that field. Actual binary upload and multi-turn session IDs
are not expressible through the available MCP execution input schema, so those
checks use the real native form/chat HTTP endpoints.

Final export/import check: both JSON definitions were imported successfully into a
fresh n8n 2.46.6 CLI database in a disposable container with `--network none` and no
existing data volumes. `list:workflow` returned exactly both expected names/IDs.
The container was removed automatically; the original deployment was unaffected.
Credentials were intentionally absent in this clean import and must be reassigned
before execution, as documented. End-to-end execution was tested on the original
credentialed instance, not on the credential-free clean import.

Retention was verified after applying the one-minute hard-delete settings and
restarting n8n: all old execution_entity rows were physically gone (zero remaining),
including the two early synthetic waiting forms, which were resumed through their
standard signed completion endpoint. No direct edits were made to n8n internal
tables. The final restarted Docker services were healthy; only n8n has a host port.
The binary-data directory contained zero files. A normal authenticated chat after
restart again returned Housing 14000 CZK and total spending 24518.75 CZK, with actual
get_monthly_summary/get_spending_summary calls and no intermediateSteps in the HTTP
response. New executions can temporarily create data until the next pruning cycle.

---

# Stage 01 verification (historical)

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
