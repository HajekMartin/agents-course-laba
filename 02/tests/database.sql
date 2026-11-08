\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path=finance,pg_catalog;
DO $$
DECLARE s jsonb; rows jsonb; imp bigint; aid bigint; cid bigint;
BEGIN
 ASSERT (SELECT data_type='numeric' AND numeric_precision=18 AND numeric_scale=2
   FROM information_schema.columns WHERE table_schema='finance' AND table_name='transactions' AND column_name='amount');
 ASSERT parse_amount('1 234,56')=1234.56;
 ASSERT parse_amount('0.10')+parse_amount('0.20')=0.30;
 ASSERT parse_date('31.10.2026')=DATE '2026-10-31';
 BEGIN PERFORM parse_amount('1,234.56'); RAISE EXCEPTION 'Ambiguous amount accepted';
 EXCEPTION WHEN raise_exception THEN ASSERT SQLERRM LIKE 'Invalid amount:%'; END;
 BEGIN PERFORM parse_date('2026-02-30'); RAISE EXCEPTION 'Invalid date accepted';
 EXCEPTION WHEN datetime_field_overflow THEN NULL; END;
 ASSERT NOT has_table_privilege('finance_reader','finance.transactions','INSERT');
 ASSERT NOT has_table_privilege('finance_reader','finance.imports','SELECT');
 ASSERT has_table_privilege('finance_reader','finance.ledger','SELECT');
 ASSERT NOT has_function_privilege('finance_reader','finance.import_statement(text,text,jsonb)','EXECUTE');
 ASSERT NOT has_schema_privilege('finance_reader','finance','CREATE');
 rows:='[{"date":"2026-01-01","amount":"-1.10","currency":"CZK","description":"Synthetic collision test","merchant":"Lidl","transaction_id":""},
         {"date":"2026-01-01","amount":"-1.10","currency":"CZK","description":"Synthetic collision test","merchant":"Lidl","transaction_id":""}]';
 s:=import_statement('synthetic-test.csv',repeat('e',64),rows);
 ASSERT (s->>'imported_transactions')::int=2,'Identical legitimate occurrences must survive';
 s:=import_statement('synthetic-test-again.csv',repeat('f',64),rows);
 ASSERT (s->>'imported_transactions')::int=0 AND (s->>'skipped_duplicates')::int=2;
 s:=import_statement('synthetic-test.csv',repeat('e',64),rows);
 ASSERT s->>'status'='duplicate_file';
 SELECT id INTO imp FROM imports WHERE file_hash=repeat('e',64);
 SELECT id INTO aid FROM accounts WHERE name='Personal' AND currency='CZK';
 SELECT id INTO cid FROM categories WHERE name='Other';
 BEGIN
   INSERT INTO transactions(account_id,transaction_date,amount,currency,description,category_id,transaction_type,deduplication_key,import_id)
   VALUES(-1,'2026-01-01',-1,'CZK','Synthetic FK test',cid,'expense',repeat('a',64),imp);
   RAISE EXCEPTION 'Missing account accepted';
 EXCEPTION WHEN foreign_key_violation THEN NULL; END;
 BEGIN
   INSERT INTO transactions(account_id,transaction_date,amount,currency,description,category_id,transaction_type,deduplication_key,import_id)
   VALUES(aid,'2026-01-01',1,'CZK','Synthetic sign test',cid,'expense',repeat('b',64),imp);
   RAISE EXCEPTION 'Invalid sign accepted';
 EXCEPTION WHEN check_violation THEN NULL; END;
 ASSERT (SELECT sum(-amount)=14000 FROM transactions t JOIN categories c ON c.id=t.category_id
   WHERE c.name='Housing' AND transaction_date>='2026-10-01' AND transaction_date<'2026-11-01');
 ASSERT (SELECT sum(-amount)=24518.75 FROM transactions
   WHERE transaction_type IN ('expense','refund') AND transaction_date>='2026-10-01' AND transaction_date<'2026-11-01');
 ASSERT (SELECT sum(amount)=45000 FROM transactions
   WHERE transaction_type='income' AND transaction_date>='2026-10-01' AND transaction_date<'2026-11-01');
 ASSERT (SELECT sum(-amount)=2720.75 FROM transactions t JOIN categories c ON c.id=t.category_id
   WHERE c.name='Groceries' AND transaction_date>='2026-10-01' AND transaction_date<'2026-11-01');
 RAISE NOTICE 'PASS: exact money, normalization, FKs, sign constraints, deduplication, reader privileges and independent October totals';
END $$;
ROLLBACK;
