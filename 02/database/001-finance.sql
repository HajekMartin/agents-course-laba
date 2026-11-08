-- Apply as the finance database owner. Re-running preserves existing transactions.
BEGIN;
CREATE SCHEMA IF NOT EXISTS finance;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA finance;
SET LOCAL search_path = finance, pg_catalog;

CREATE TABLE IF NOT EXISTS accounts (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name text NOT NULL,
  currency text NOT NULL CHECK (currency IN ('CZK','EUR','USD','GBP','PLN','CHF')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (name, currency), UNIQUE (id, currency)
);
CREATE TABLE IF NOT EXISTS categories (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name text NOT NULL UNIQUE,
  type text NOT NULL CHECK (type IN ('expense','income','transfer','mixed'))
);
INSERT INTO categories(name,type) VALUES
 ('Housing','expense'),('Groceries','expense'),('Restaurants','expense'),
 ('Transport','expense'),('Shopping','expense'),('Healthcare','expense'),
 ('Subscriptions','expense'),('Entertainment','expense'),('Income','income'),
 ('Transfers','transfer'),('Other','mixed') ON CONFLICT (name) DO NOTHING;

CREATE TABLE IF NOT EXISTS categorization_rules (
  merchant_pattern text PRIMARY KEY,
  category_id bigint NOT NULL REFERENCES categories(id),
  priority integer NOT NULL DEFAULT 100
);
INSERT INTO categorization_rules(merchant_pattern,category_id,priority)
SELECT v.pattern,c.id,v.priority FROM (VALUES
 ('(^|[^a-z])(lidl|albert|kaufland)([^a-z]|$)','Groceries',10),
 ('(^|[^a-z])(netflix|spotify)([^a-z]|$)','Subscriptions',20),
 ('(^|[^a-z])(shell|omv|dpp)([^a-z]|$)','Transport',30),
 ('(^|[^a-z])alza([^a-z]|$)','Shopping',40),
 ('(^|[^a-z])(bistro|restaurant|cafe)([^a-z]|$)','Restaurants',50),
 ('(^|[^a-z])synthetic rent([^a-z]|$)','Housing',60),
 ('(^|[^a-z])synthetic pharmacy([^a-z]|$)','Healthcare',70),
 ('(^|[^a-z])synthetic cinema([^a-z]|$)','Entertainment',80)
) v(pattern,category,priority) JOIN categories c ON c.name=v.category
ON CONFLICT (merchant_pattern) DO UPDATE SET category_id=excluded.category_id,priority=excluded.priority;

CREATE TABLE IF NOT EXISTS imports (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  file_name text NOT NULL CHECK (length(file_name)<=255),
  file_hash text NOT NULL UNIQUE CHECK (file_hash ~ '^[a-f0-9]{64}$'),
  imported_at timestamptz NOT NULL DEFAULT now(),
  processed_count integer NOT NULL DEFAULT 0 CHECK (processed_count>=0),
  imported_count integer NOT NULL DEFAULT 0 CHECK (imported_count>=0),
  skipped_count integer NOT NULL DEFAULT 0 CHECK (skipped_count>=0),
  invalid_count integer NOT NULL DEFAULT 0 CHECK (invalid_count>=0),
  status text NOT NULL CHECK (status IN ('completed','partial','rejected')),
  errors jsonb NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS transactions (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id bigint NOT NULL,
  transaction_date date NOT NULL,
  amount numeric(18,2) NOT NULL CHECK (amount<>0),
  currency text NOT NULL,
  description text NOT NULL CHECK (length(description) BETWEEN 1 AND 500),
  merchant text CHECK (length(merchant)<=160),
  category_id bigint NOT NULL REFERENCES categories(id),
  transaction_type text NOT NULL CHECK (transaction_type IN ('expense','income','refund','transfer')),
  source_reference text CHECK (length(source_reference)<=160),
  deduplication_key text NOT NULL UNIQUE CHECK (deduplication_key ~ '^[a-f0-9]{64}$'),
  import_id bigint NOT NULL REFERENCES imports(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (account_id,currency) REFERENCES accounts(id,currency),
  CHECK ((transaction_type='expense' AND amount<0) OR
         (transaction_type IN ('income','refund') AND amount>0) OR transaction_type='transfer')
);
CREATE INDEX IF NOT EXISTS transactions_date_idx ON transactions(transaction_date);
CREATE INDEX IF NOT EXISTS transactions_category_date_idx ON transactions(category_id,transaction_date);
CREATE INDEX IF NOT EXISTS transactions_merchant_idx ON transactions(lower(merchant));
CREATE UNIQUE INDEX IF NOT EXISTS transactions_source_idx ON transactions(account_id,source_reference)
 WHERE source_reference IS NOT NULL;

CREATE OR REPLACE FUNCTION clean_text(v text) RETURNS text LANGUAGE sql IMMUTABLE
RETURN btrim(regexp_replace(coalesce(v,''),'[[:space:]]+',' ','g'));

-- Strict syntax before NUMERIC cast: no floating point and no ambiguous grouping.
CREATE OR REPLACE FUNCTION parse_amount(v text) RETURNS numeric LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE s text := btrim(translate(coalesce(v,''),chr(160)||chr(8239),'  '));
BEGIN
 IF s !~ '^[+-]?([0-9]+|[0-9]{1,3}( [0-9]{3})+)([.,][0-9]{1,2})?$' THEN
   RAISE EXCEPTION 'Invalid amount: use signed decimal with at most two decimal places';
 END IF;
 RETURN replace(replace(s,' ',''),',','.')::numeric(18,2);
END $$;
CREATE OR REPLACE FUNCTION parse_date(v text) RETURNS date LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE d date; s text:=btrim(v);
BEGIN
 IF s ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN d:=s::date;
 ELSIF s ~ '^[0-9]{2}\.[0-9]{2}\.[0-9]{4}$' THEN
   d:=to_date(s,'DD.MM.YYYY');
   IF to_char(d,'DD.MM.YYYY')<>s THEN RAISE EXCEPTION 'Invalid calendar date'; END IF;
 ELSE RAISE EXCEPTION 'Invalid date: use YYYY-MM-DD or DD.MM.YYYY'; END IF;
 IF d<'1900-01-01' OR d>'2100-12-31' THEN RAISE EXCEPTION 'Date outside supported range'; END IF;
 RETURN d;
END $$;

-- One call is one atomic import. Invalid rows are reported; valid rows are committed.
CREATE OR REPLACE FUNCTION import_statement(p_name text,p_hash text,p_rows jsonb)
RETURNS jsonb LANGUAGE plpgsql SET search_path=finance,pg_catalog AS $$
DECLARE
 imp bigint; r jsonb; n integer:=0; added integer:=0; skipped integer:=0; invalid integer:=0;
 errs jsonb:='[]'; a numeric; d date; cur text; descr text; merch text; ref text; typ text;
 cat text; aid bigint; cid bigint; key text; fingerprint text; occurrence integer; seen jsonb:='{}';
 existing transactions%ROWTYPE; old imports%ROWTYPE; row_count integer; row_error text;
 required text[]:=ARRAY['date','amount','currency','description','merchant','transaction_id'];
BEGIN
 IF jsonb_typeof(p_rows)<>'array' OR jsonb_array_length(p_rows)>5000 THEN
   RAISE EXCEPTION 'Expected an array of at most 5000 transactions'; END IF;
 IF p_hash !~ '^[a-f0-9]{64}$' THEN RAISE EXCEPTION 'Invalid SHA256 file hash'; END IF;
 -- Serialize concurrent imports, including overlapping statements.
 PERFORM pg_advisory_xact_lock(20260202);
 SELECT * INTO old FROM imports WHERE file_hash=p_hash;
 IF FOUND THEN RETURN jsonb_build_object('file_name',p_name,'processed_rows',old.processed_count,
   'imported_transactions',0,'skipped_duplicates',old.imported_count+old.skipped_count,
   'invalid_rows',old.invalid_count,'status','duplicate_file','errors',old.errors); END IF;
 INSERT INTO imports(file_name,file_hash,status) VALUES(left(p_name,255),p_hash,'rejected') RETURNING id INTO imp;
 IF jsonb_array_length(p_rows)=0 OR NOT (p_rows->0 ?& required) THEN
   errs:=jsonb_build_array(jsonb_build_object('row',1,'field','header','message','Missing canonical columns: date, amount, currency, description, merchant, transaction_id'));
   invalid:=jsonb_array_length(p_rows); n:=invalid;
 ELSE
 FOR r IN SELECT value FROM jsonb_array_elements(p_rows) LOOP
   n:=n+1; row_error:=NULL;
   BEGIN
     IF NOT (r ?& required) THEN RAISE EXCEPTION 'Missing required columns'; END IF;
     BEGIN a:=parse_amount(r->>'amount'); EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'Invalid amount'; END;
     IF a=0 THEN RAISE EXCEPTION 'Zero amount is not supported'; END IF;
     BEGIN d:=parse_date(r->>'date'); EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'Invalid transaction date'; END;
     cur:=upper(clean_text(r->>'currency'));
     IF cur NOT IN ('CZK','EUR','USD','GBP','PLN','CHF') THEN RAISE EXCEPTION 'Unsupported currency'; END IF;
     descr:=clean_text(r->>'description'); merch:=nullif(clean_text(r->>'merchant'),'');
     ref:=nullif(clean_text(r->>'transaction_id'),'');
     IF length(descr) NOT BETWEEN 1 AND 500 OR length(merch)>160 OR length(ref)>160 THEN
       RAISE EXCEPTION 'Empty description or text exceeds length limit'; END IF;
     typ:=lower(nullif(clean_text(r->>'transaction_type'),''));
     typ:=coalesce(typ,CASE WHEN a<0 THEN 'expense' ELSE 'income' END);
     IF typ NOT IN ('expense','income','refund','transfer') OR
        (typ='expense' AND a>0) OR (typ IN ('income','refund') AND a<0) THEN
       RAISE EXCEPTION 'Invalid transaction_type or incompatible amount sign'; END IF;
     INSERT INTO accounts(name,currency) VALUES('Personal',cur) ON CONFLICT DO NOTHING;
     SELECT id INTO aid FROM accounts WHERE name='Personal' AND currency=cur;
     cat:=CASE typ WHEN 'income' THEN 'Income' WHEN 'transfer' THEN 'Transfers' ELSE NULL END;
     IF cat IS NULL THEN SELECT c.name INTO cat FROM categorization_rules cr JOIN categories c ON c.id=cr.category_id
       WHERE lower(coalesce(merch,'')) ~ cr.merchant_pattern ORDER BY priority,merchant_pattern LIMIT 1; END IF;
     SELECT id INTO cid FROM categories WHERE name=coalesce(cat,'Other');
     fingerprint:=encode(digest(jsonb_build_array(aid,d,a::text,cur,lower(descr),lower(merch),typ)::text,'sha256'),'hex');
     occurrence:=coalesce((seen->>fingerprint)::integer,0)+1;
     seen:=jsonb_set(seen,ARRAY[fingerprint],to_jsonb(occurrence));
     key:=encode(digest(CASE WHEN ref IS NOT NULL THEN jsonb_build_array(aid,'bank-id',ref)::text
         ELSE jsonb_build_array(fingerprint,occurrence)::text END,'sha256'),'hex');
     SELECT * INTO existing FROM transactions WHERE deduplication_key=key;
     IF FOUND AND (existing.transaction_date<>d OR existing.amount<>a OR existing.currency<>cur OR
        existing.description<>descr OR existing.merchant IS DISTINCT FROM merch OR existing.transaction_type<>typ) THEN
       RAISE EXCEPTION 'Conflicting transaction identifier: existing transaction was preserved'; END IF;
     INSERT INTO transactions(account_id,transaction_date,amount,currency,description,merchant,category_id,
       transaction_type,source_reference,deduplication_key,import_id)
     VALUES(aid,d,a,cur,descr,merch,cid,typ,ref,key,imp) ON CONFLICT DO NOTHING;
     GET DIAGNOSTICS row_count=ROW_COUNT;
     IF row_count=1 THEN added:=added+1; ELSE skipped:=skipped+1; END IF;
   EXCEPTION WHEN OTHERS THEN
     invalid:=invalid+1;
     -- Return controlled validation messages only; database errors can contain private row values.
     row_error:=CASE WHEN SQLERRM IN ('Invalid amount','Zero amount is not supported','Invalid transaction date',
       'Unsupported currency','Empty description or text exceeds length limit',
       'Invalid transaction_type or incompatible amount sign','Missing required columns',
       'Conflicting transaction identifier: existing transaction was preserved') THEN SQLERRM ELSE 'Row failed database validation' END;
     IF jsonb_array_length(errs)<100 THEN errs:=errs||jsonb_build_object('row',n+1,'message',row_error); END IF;
   END;
 END LOOP;
 END IF;
 UPDATE imports SET processed_count=n,imported_count=added,skipped_count=skipped,invalid_count=invalid,
   status=CASE WHEN jsonb_array_length(errs)>0 AND added+skipped=0 THEN 'rejected'
     WHEN invalid=0 THEN 'completed' ELSE 'partial' END,errors=errs WHERE id=imp;
 RETURN (SELECT jsonb_build_object('file_name',file_name,'processed_rows',processed_count,
   'imported_transactions',imported_count,'skipped_duplicates',skipped_count,'invalid_rows',invalid_count,
   'status',status,'errors',errors,'error_details_capped_at',100) FROM imports WHERE id=imp);
END $$;

-- Positive money is incoming; negative money is outgoing. Refunds reduce net spending.
CREATE OR REPLACE VIEW ledger AS
SELECT t.transaction_date,t.amount,t.currency,t.description,t.merchant,t.transaction_type,c.name AS category,
 CASE WHEN t.transaction_type IN ('expense','refund') THEN -t.amount ELSE 0::numeric END AS spending,
 CASE WHEN t.transaction_type='income' THEN t.amount ELSE 0::numeric END AS income,
 CASE WHEN t.transaction_type<>'transfer' THEN t.amount ELSE 0::numeric END AS net
FROM transactions t JOIN categories c ON c.id=t.category_id;

-- No default PUBLIC execution of application routines.
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA finance FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA finance FROM PUBLIC;
COMMIT;
