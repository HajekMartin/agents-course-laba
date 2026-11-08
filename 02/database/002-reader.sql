\set ON_ERROR_STOP on
\getenv finance_db FINANCE_DB_NAME
\getenv reader_password FINANCE_READER_PASSWORD
SELECT format('CREATE ROLE finance_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'reader_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname='finance_reader') \gexec
GRANT CONNECT ON DATABASE :"finance_db" TO finance_reader;
\connect :finance_db
GRANT USAGE ON SCHEMA finance TO finance_reader;
GRANT SELECT ON finance.ledger TO finance_reader;
ALTER ROLE finance_reader SET default_transaction_read_only=on;
ALTER ROLE finance_reader SET statement_timeout='10s';
ALTER ROLE finance_reader SET search_path=finance,pg_catalog;
