-- Only on the explicitly authorized disposable Gate B database, as mwcp_app.
-- Each negative must raise 42501; any success or other SQLSTATE aborts psql.
\set ON_ERROR_STOP on
DO $$
BEGIN
  IF current_user <> 'mwcp_app' THEN
    RAISE EXCEPTION 'Permission tests require mwcp_app';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=current_user
             AND (rolsuper OR rolcreatedb OR rolcreaterole)) THEN
    RAISE EXCEPTION 'Unexpected elevated app role';
  END IF;
  BEGIN
    CREATE TABLE public._perm_probe_should_fail(id int);
    RAISE EXCEPTION 'CREATE TABLE unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    DROP TABLE public.tasks;
    RAISE EXCEPTION 'DROP TABLE unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    CREATE ROLE _mwcp_gateb_should_fail;
    RAISE EXCEPTION 'CREATE ROLE unexpectedly succeeded';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $$;
-- Positive DML must work; always roll it back.
BEGIN;
INSERT INTO work_items(title,kind,created_by)
VALUES ('Gate B permission test','task','gateb-verifier');
SELECT count(*) FROM work_items;
ROLLBACK;
