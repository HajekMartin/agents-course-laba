# Workflow deliverables

Stage 01 intentionally contains no workflow JSON. Later stages will place tested,
importable n8n exports here, including one main workflow demonstrating the assignment.

Export completed changes from the running development instance and review the JSON
before committing. Remove pinned execution data, bank records, tokens, passwords,
and sensitive inline node parameters. Credential references may contain names and
IDs; recreate credentials locally after import. Never export decrypted credentials.

See [the development guide](../docs/development.md#workflow-export-and-import).
