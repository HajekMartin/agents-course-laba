# Development and operations

Run all Compose commands from `02/`. This project is named `finance-assistant-02`
and does not share networks, volumes, databases, or service lifecycle with Assignment 01.

## Startup and logs

First generate `.env` following the README. Then:

```bash
docker compose config --quiet
docker compose up -d --wait --wait-timeout 180
docker compose ps
docker compose logs --tail=100 n8n postgres
docker compose logs -f n8n
```

`docker compose up -d` also works; `--wait` additionally waits for healthchecks.
PostgreSQL has a TCP readiness check, and n8n checks `/healthz/readiness` from
inside its container. No startup delay script is used. A container can be healthy
before owner setup, MCP consent, or Unsloth configuration is complete.

Avoid posting private logs or the output of unrestricted `docker compose config`
or `docker inspect`: environment values can include secrets. Prefer `config --quiet`
for routine configuration validation.

## Workflow development cycle

1. Start Compose and wait for readiness.
2. Open n8n in the browser and complete initial owner setup.
3. Enable **Settings → Instance-level MCP**.
4. Connect local Codex and approve OAuth permissions explicitly.
5. Inspect available tools and complete an authenticated read-only request.
6. Ask Codex to create/modify workflows through MCP using its live
   SDK guidance and tool schemas. Review which resources and scopes it can access.
7. Validate before saving, test with synthetic data, and inspect execution results.
8. Export completed workflow JSON into `workflows/`.
9. Inspect exports for secrets and financial/pinned data; remove them and inspect
   the resulting Git diff.
10. Commit sanitized JSON definitions and related documentation.

The instance is the development environment. Exported, reviewed JSON files are
the source-controlled deliverables. Stage 02 exports are `finance-import.json` and `finance-agent.json`; see the README for credential reassignment.
See [codex-mcp.md](codex-mcp.md) for authentication and execution permissions.

After an MCP edit, compare the actual CLI export with the previous definition.
The installed Chat Trigger 1.5 schema marks `options` visible only when public is
false; an MCP graph roundtrip can drop existing hosted-chat options. Reapply the
complete Finance Chat parameters explicitly in the final update, including
`autoSaveHighlightedData=false`, the localhost origin and Czech interface text,
then publish and read back the actual export. Keep Authentication=None for the
authorized anonymous local demo and responseMode=lastNode so the evidence check
and exact table formatter determine the visible answer.

Stage 02 application setup is `node config/setup-finance.mjs`. It applies the finance
migration and creates encrypted credentials; refer to the main README for current
workflow operation, tests, privacy settings, and limitations.

## Database inspection

The commands below use container variables rather than placing passwords on the
host command line. PostgreSQL's local socket is available to the container admin;
host TCP connections still require SCRAM authentication and no host port is published.

```bash
# Bootstrap administration and database list.
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "\l"'

# Internal n8n tables (official application migrations).
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$N8N_DB_NAME" -c "\dt public.*"'

# Finance schema (initially empty before config/setup-finance.mjs).
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$FINANCE_DB_NAME" -c "\dn" -c "\dt finance.*"'

# Authenticate with the non-superuser finance login over TCP.
docker compose exec postgres sh -c 'PGPASSWORD="$FINANCE_DB_PASSWORD" psql -h 127.0.0.1 -U "$FINANCE_DB_USER" -d "$FINANCE_DB_NAME" -c "SELECT current_user, current_database(), current_schema();"'
```

The last command should report `finance_app`, `finance`, `finance` with defaults.
Application roles cannot connect to the other application database because public
database privileges were revoked. The server administrator can inspect both.
Do not grant the bootstrap superuser to a future workflow.

## Initialization and configuration changes

`database/init/10-create-databases.sql` is mounted read-only under the official image's
`/docker-entrypoint-initdb.d`. The entrypoint runs it only when the data directory
is empty. It creates roles, databases, and the finance schema without finance tables.
The psql script safely quotes names/passwords and stops on SQL errors. It can be rerun
by an administrator for the same names; existing passwords are not changed.

If initialization fails on a new volume, inspect `docker compose logs postgres`.
The image skips automatic initialization once PostgreSQL's data directory exists,
so a restart alone will not retry the script. After fixing the configuration,
an administrator can rerun the idempotent bootstrap for the intended names:

```bash
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/10-create-databases.sql'
docker compose up -d --wait --wait-timeout 180
```

This does not reconcile renamed databases or rotate existing passwords; inspect
existing storage before using it. Do not delete volumes containing valuable data.

Editing an environment variable does **not** alter a password/database already
stored in the persistent volume. For rotation, change the role password through an
authenticated administrator session, update private `.env` and affected local
credentials, then recreate affected services. Changing `N8N_ENCRYPTION_KEY` alone
makes existing encrypted credentials unreadable; preserve it and follow official
rotation guidance if rotation is ever necessary.

After changing an endpoint, model ID, timezone, or host-side port:

```bash
docker compose config --quiet
docker compose up -d --wait --wait-timeout 180
```

## Workflow export and import

Use the editor workflow menu **Download** to export a workflow,
then save the reviewed JSON as `workflows/<meaningful-name>.json`. The editor's
**Import from File** action imports the definition. Recreate credentials locally
and verify inactive imports before publishing or enabling MCP access.

For reproducible CLI export without host n8n, use a private temporary directory
in the existing n8n volume and copy it out after success:

```bash
# Export only the intended workflows when unrelated workflows exist.
docker compose exec -T n8n n8n export:workflow --all --separate \
  --output=/home/node/.n8n/workflow-exports/
mkdir -p exports
docker compose cp n8n:/home/node/.n8n/workflow-exports/. ./exports/
```

These Server CLI flags were checked against the selected image's help and the
[official CLI reference](https://docs.n8n.io/hosting/cli-commands/).

`exports/` is ignored because unreviewed exports can contain sensitive information.
Copy only reviewed deliverables to `workflows/`. Prefer exporting one workflow
by `--id=<workflow-id>` with `--output=/tmp/workflow.json` when the instance contains
unrelated workflows. An example CLI import:

```bash
docker compose cp ./workflows/<reviewed-workflow>.json n8n:/tmp/workflow.json
docker compose exec -T n8n n8n import:workflow --input=/tmp/workflow.json
```

Substitute real filenames/IDs. Check the owner/project and credential references
after import. Restart n8n if needed for CLI-imported changes to appear, and confirm
the imported workflow is inactive before testing. Export JSON can include pinned
execution data, inline secrets in HTTP nodes, credential IDs/names, and sensitive
parameters even when credential values themselves are not exported. Never run
`export:credentials --decrypted` or commit execution databases, private statements,
credentials, or raw exports. Validate imports in the UI/MCP before use.

## Persistence and backups

Named volumes are `finance-assistant-02_postgres_data` and
`finance-assistant-02_n8n_data` for the default project name. Inspect attachments:

```bash
docker volume inspect finance-assistant-02_postgres_data finance-assistant-02_n8n_data
docker inspect "$(docker compose ps -q n8n)" --format '{{json .Mounts}}'
docker inspect "$(docker compose ps -q postgres)" --format '{{json .Mounts}}'
```

`docker compose stop`, container recreation, and `docker compose down` preserve
named volumes. **`docker compose down --volumes` destroys this project's persistent
data.** Never use it as routine shutdown or troubleshooting on valuable storage.
Changing the Compose project name selects different volumes and can look like data
loss even though the original volumes still exist.

For a consistent local backup, stop n8n so its metadata and instance files are not
changing, dump both application databases and roles, then archive the n8n directory:

```bash
umask 077
mkdir -p backups
docker compose stop n8n
docker compose exec -T postgres sh -c 'pg_dumpall -U "$POSTGRES_USER" --globals-only' > backups/roles.sql
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$N8N_DB_NAME" -Fc' > backups/n8n.dump
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$FINANCE_DB_NAME" -Fc' > backups/finance.dump
docker compose run --rm --no-deps -T --entrypoint tar n8n \
  -C /home/node/.n8n -czf - . > backups/n8n-data.tar.gz
docker compose up -d --wait --wait-timeout 180
```

Keep the matching `.env` and encryption key separately in secure backup storage.
Role dumps contain password verifiers; database dumps and instance files may
contain financial data and authentication secrets. `backups/` is ignored. Check
every command's exit status and archive integrity before relying on a backup;
these fixed filenames overwrite older local backups, so archive dated copies first.

A restore needs matching roles, both database dumps, the n8n files, and the original
encryption key. Restore using a compatible PostgreSQL version with n8n stopped;
on a clean deployment the initialization already creates roles/databases, so review
the globals dump and reconcile existing roles rather than blindly replaying it.
Use `pg_restore --clean --if-exists` into the intended application databases and
restore the n8n archive with ownership readable by the image's `node` user. Test a
restore on disposable storage before trusting the procedure with real data.

## Updating n8n and PostgreSQL

1. Back up storage and the matching encryption key. Review official release notes,
   breaking changes, and current security fixes.
2. Select an exact stable n8n tag supporting the required MCP tools; update the
   image in `compose.yaml` and versioned setup examples in the README. Do not use
   `latest`, `stable`, beta, or prerelease tags as a version pin.
3. Pull and recreate only the intended service:

   ```bash
   docker compose pull n8n
   docker compose up -d --wait --wait-timeout 180 n8n
   docker compose exec -T n8n n8n --version
   ```

4. Verify readiness, the editor, an authenticated MCP request and required tools.
   Repeat the documented import/database/chat tests, then export reviewed definitions.

n8n may migrate its internal database. Downgrading only the image is not a reliable
rollback; restore the compatible database/files/key backup when required. Version
notifications are disabled intentionally, so schedule manual update review.
PostgreSQL patch updates stay within major 17. A major-version change requires a
supported database migration/restore and review of official volume path changes;
do not point a new major at the existing data directory.

## Shutdown

```bash
# Preserve containers and all data.
docker compose stop

# Remove this project's containers/network; named volumes remain.
docker compose down
```

Restart with `docker compose up -d`. The `unless-stopped` policy respects explicit
stops. Nothing here stops or changes Assignment 01 or the host-managed model.
