# Connect local Codex to n8n

This deployment uses n8n **2.46.6 Community** and its official built-in instance-level
MCP server, not a workflow MCP Server Trigger or a third-party bridge.
Workflow building through instance MCP is documented from n8n 2.13.0 onward.

Sources verified for this setup:
[n8n instance MCP](https://docs.n8n.io/connect/connect-to-n8n-mcp-server),
[n8n Codex examples](https://docs.n8n.io/connect/connect-to-n8n-mcp-server/mcp-client-examples#connecting-codex-cli-to-n8n-mcp-server),
[n8n MCP tool reference](https://docs.n8n.io/connect/connect-to-n8n-mcp-server/mcp-server-tools-reference),
[official Codex MCP documentation](https://developers.openai.com/codex/mcp).
The installed CLI's `codex mcp add --help` and `codex mcp login --help` also confirm
the commands and environment-based bearer-token option below.

## 1. Start the instance and create its owner

```bash
cd 02
docker compose up -d --wait --wait-timeout 180
```

If `.env` does not exist, first follow the README's environment generation steps.
Visit **http://localhost:5678**, complete owner setup, and sign in. There is no
automatic owner creation or browser authentication bypass.

## 2. Enable instance-level MCP

As owner (or an authorized instance administrator):

1. Open **Settings → Instance-level MCP**.
2. Select **Enable MCP access**.
3. Under **Connection details**, select **Connect**.
4. On the **OAuth (recommended)** tab, select **Codex** in **Your client**.
5. Copy the **Server URL** and compare it to:

   ```text
   http://localhost:5678/mcp-server/http
   ```

The module is available because Compose leaves `N8N_DISABLED_MODULES` empty.
Do not set it to `mcp`. Module availability does not enable instance access or
authenticate a client. No MCP token belongs in Compose or `.env.example`.
If you change the host port, copy the updated URL from the running settings page.

## 3. Register Codex and authenticate with OAuth

Run Codex **locally on the same workstation** as Docker:

```bash
codex --version
codex mcp add n8n --url "http://localhost:5678/mcp-server/http"
codex mcp login n8n
codex mcp list
```

`add` registers a Streamable HTTP connection. `login` starts OAuth and requires
you to sign in and approve the requested permissions in your browser. Approve
read access plus building/editing and execution only as needed for the intended
development work. A read-only grant is insufficient for creating workflows.
Do not assume owner privileges automatically grant every client scope.

The pinned server maps workflow discovery/validation to `workflow:read`, creation
and modification to `workflow:write`, tests to `workflow:execute`, and result
inspection to `execution:read`. If the client's default scope request is unsuitable,
request these explicitly and review them in the browser:

```bash
codex mcp login n8n --scopes workflow:read,workflow:write,workflow:execute,execution:read
```

Node credential discovery additionally needs `credential:read` if that capability
is requested in a later stage. Grant additional scopes only for the needed work.

The non-secret equivalent in your **user** `~/.codex/config.toml` is:

```toml
[mcp_servers.n8n]
url = "http://localhost:5678/mcp-server/http"
```

Then run `codex mcp login n8n`. Current Codex supports HTTP MCP directly; do not
add the obsolete `experimental_use_rmcp_client` flag shown for older clients.
OAuth credentials are managed by Codex outside this repository.

For a restricted OAuth callback policy, open **Settings → Instance-level MCP →
Access → Allowed callback URLs**. Permit the actual trusted loopback redirect URL
used by your Codex CLI, including its port and path; do not assume a fixed callback
port. A fixed `mcp_oauth_callback_port` can be configured in your user Codex settings
if needed. Do not replace this with a public tunnel. Review the browser's requested
permissions and the exact redirect before approving.

Restart the Codex IDE extension or open a new CLI session after configuration.
The CLI and IDE normally share user MCP configuration. A remote/cloud Codex runtime
cannot reach your workstation's `localhost`; use local Codex for this deployment.

## 4. Official API-key alternative

Use this if local OAuth is unsupported by your client build or is blocked by the
callback policy. Keep n8n authentication enabled and the endpoint on loopback.

1. In **Settings → Instance-level MCP → Connection details → Connect**, open
   **API key**. Copy the personal MCP access token and Server URL. This is the
   **MCP token**, not a general n8n REST API key or the owner password.
2. Supply the token to the local Codex process through a private environment
   variable named `N8N_MCP_TOKEN`. For example, in Bash/WSL, enter it silently:

   ```bash
   read -r -s -p 'n8n MCP token: ' N8N_MCP_TOKEN
   printf '\n'
   export N8N_MCP_TOKEN
   ```

   In macOS zsh, use `read -r -s 'N8N_MCP_TOKEN?n8n MCP token: '` followed by
   `printf '\n'` and `export N8N_MCP_TOKEN` instead. Do not type the token into
   a command argument or commit it to a shell script.
3. If replacing an existing OAuth registration, remove that named server first:

   ```bash
   codex mcp remove n8n
   codex mcp add n8n --url "http://localhost:5678/mcp-server/http" \
     --bearer-token-env-var N8N_MCP_TOKEN
   codex
   ```

The resulting non-secret configuration is:

```toml
[mcp_servers.n8n]
url = "http://localhost:5678/mcp-server/http"
bearer_token_env_var = "N8N_MCP_TOKEN"
```

This sends the official `Authorization: Bearer` header without embedding the
token in a file. Do not run `codex mcp login` for this mode. Start Codex in the same
environment; IDE processes launched earlier do not inherit a terminal's new variable.
Use a private process environment/secret manager if the IDE needs this alternative.
`unset N8N_MCP_TOKEN` after finishing. Rotate the token in n8n if lost or disclosed;
rotation invalidates the previous token. API-key clients are not listed as OAuth
connected clients, and their access is tied to their n8n user.

## 5. Verify an authenticated connection

`codex mcp list` proves configuration only. In a **new connected Codex session**:

1. Use `/mcp` to inspect connection status and available tools.
2. Ask: “List the tools offered by the n8n MCP server, then call search_workflows
   without creating or changing anything.”
3. Confirm the tool call returns an authenticated result. An empty workflow list
   is expected in Stage 01 and is a valid result.
4. Inspect whether the authorized tool list supports the intended later-stage work:

   | Task | Tools to look for in this pinned version |
   | --- | --- |
   | Discover/inspect | `search_workflows`, `get_workflow_details` |
   | Read SDK guidance | `get_workflow_sdk_reference`, node search/detail tools |
   | Validate/build | `validate_workflow`, `create_workflow_from_code`, `update_workflow` |
   | Test/execute | `test_workflow`, `execute_workflow` |
   | Inspect results | `get_workflow_execution`, `search_workflow_executions` |

Use live tool schemas as the authority. For example, `validate_workflow` validates
Workflow SDK code rather than arbitrary exported JSON. Creation accepts SDK code;
updates use the partial operations defined by the server. Follow SDK guidance and
validate before saving. Missing tools or denied calls require reviewing scopes,
user permissions, client tool filters, and version—not an authentication bypass.

Stage 01 intentionally stops at read-only discovery. Do not create a workflow just
to demonstrate a successful infrastructure connection. Record actual tool discovery
and a successful authenticated request before claiming MCP connectivity works.

## 6. Later workflow development and permissions

Enable access for each existing workflow in its **Settings → Available in MCP**
setting (or the editor menu's **Enable MCP access** action). `search_workflows` can
return previews of workflows the user can see even before per-workflow exposure;
full inspection, modification, and execution require workflow MCP availability.
Workflows created through the MCP builder are automatically marked available in MCP.

User-level permissions and client authorization still apply. All clients for a user
share that user's exposed workflows; do not assume separate per-client workflow lists.
Review **Connected clients** and revoke OAuth access when no longer needed.

For future tests, prefer synthetic pin data. `test_workflow` can execute ordinary
logic and credential-free I/O; it is not a guaranteed side-effect-free sandbox.
`execute_workflow` with `executionMode: "manual"` targets the current draft and
supported triggers; production mode needs the published version. Inspect returned
execution IDs with the execution tools. Trigger support, execution scope, and
workflow access all matter; human-in-the-loop and multi-step form execution have
documented limitations. Do not publish or run workflows without the user's scope.

Export tested workflow JSON into `workflows/`, sanitize it, and commit it. The
running database is a development environment, not the only copy of deliverables.

## Troubleshooting

| Symptom | Check / action |
| --- | --- |
| Connection refused | `docker compose ps`, readiness, correct host port; run Codex locally |
| MCP settings missing | Check `n8n --version` inside the container; `N8N_DISABLED_MODULES` must not contain `mcp`; sign in as owner |
| Endpoint absent/disabled | Activate instance MCP in the UI; use `/mcp-server/http`, not `/mcp` or an MCP Trigger URL |
| HTTP 401/403 | Finish OAuth/consent or supply the correct MCP bearer token; review requested scopes |
| OAuth redirect rejected | Inspect the actual loopback callback and trusted URL policy; update CLI or use the official token alternative |
| Read works but build/execute fails | Review granted client permissions, per-workflow exposure and n8n user permissions |
| Old tool list | Restart the Codex session/IDE after configuration or version changes |
| No workflows found | Expected before later stages; do not add placeholder workflows |
| Token lost | Generate/rotate it in the MCP API-key tab and update the private process environment |
| Works in terminal but not IDE | Restart IDE and inspect its selected config/process environment |

Unauthenticated HTTP probes can establish route protection or feature presence;
they cannot establish an authenticated MCP connection.
