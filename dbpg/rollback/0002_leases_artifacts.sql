-- DESTRUCTIVE: disposable Gate B database only; stop API first.
DROP TABLE artifacts;
DROP TABLE task_leases;
DROP FUNCTION audit_retention_days();
