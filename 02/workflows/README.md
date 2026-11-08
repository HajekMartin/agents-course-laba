# Workflow exports

These are actual sanitized n8n 2.46.6 exports from the running instance:

- `finance-import.json`: Finance - Import Bank Statement, supporting CSV/XLSX and text PDF, with a permanent
  production form and an upload-another result link.
- `finance-agent.json`: Finance - AI Assistant, including four native PostgreSQL tools.

Import through the n8n editor or documented Server CLI. Both exports are inactive
and contain no credential values, pinned records or execution data. Create or reassign
the database and local-model credential types described in the main README, choose the model actually
listed by the local Unsloth API, and publish. Webhook IDs can change on a clean
instance; use the URLs shown by its triggers. No subworkflows are required.

The form and chat triggers use Authentication = None for the localhost demo.
No separate form/chat credential is needed.

Assign the local Unsloth credential to **PDF Local Model** as well as the agent
model. The import workflow also uses its database credential to check known file
hashes before extracting files.
