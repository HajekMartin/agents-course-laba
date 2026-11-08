\set ON_ERROR_STOP on

-- Executed by the official PostgreSQL entrypoint on an empty data volume.
-- psql reads secrets from the environment, never from command-line arguments.
\getenv admin_user POSTGRES_USER
\getenv n8n_db N8N_DB_NAME
\getenv n8n_user N8N_DB_USER
\getenv n8n_password N8N_DB_PASSWORD
\getenv finance_db FINANCE_DB_NAME
\getenv finance_user FINANCE_DB_USER
\getenv finance_password FINANCE_DB_PASSWORD

SELECT bool_and(value ~ '^[a-z_][a-z0-9_]{0,62}$') AS valid_identifiers
FROM (VALUES (:'admin_user'), (:'n8n_db'), (:'n8n_user'), (:'finance_db'), (:'finance_user')) AS names(value) \gset
\if :valid_identifiers
\else
  DO $$ BEGIN
    RAISE EXCEPTION 'Database and role names must be lowercase SQL identifiers (maximum 63 characters).';
  END $$;
\endif

SELECT :'n8n_db' <> :'finance_db'
   AND :'n8n_db' NOT IN ('postgres', 'template0', 'template1')
   AND :'finance_db' NOT IN ('postgres', 'template0', 'template1')
   AND :'n8n_user' <> :'finance_user'
   AND :'n8n_user' <> :'admin_user'
   AND :'finance_user' <> :'admin_user' AS distinct_names \gset
\if :distinct_names
\else
  DO $$ BEGIN
    RAISE EXCEPTION 'Use distinct application databases and roles, separate from bootstrap/system names.';
  END $$;
\endif

-- format(%I/%L) safely quotes identifiers and values. Re-running with the same
-- names is harmless but intentionally does not rotate existing role passwords.
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'n8n_user', :'n8n_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'n8n_user') \gexec
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'finance_user', :'finance_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'finance_user') \gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'n8n_db', :'n8n_user')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'n8n_db') \gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'finance_db', :'finance_user')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'finance_db') \gexec
REVOKE ALL ON DATABASE :"n8n_db" FROM PUBLIC;
REVOKE ALL ON DATABASE :"finance_db" FROM PUBLIC;

\connect :n8n_db
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

\connect :finance_db
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA IF NOT EXISTS finance AUTHORIZATION :"finance_user";
ALTER ROLE :"finance_user" IN DATABASE :"finance_db" SET search_path = finance;
