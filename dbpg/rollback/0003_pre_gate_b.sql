-- DESTRUCTIVE: disposable Gate B database only; stop API first.
ALTER TABLE tasks DROP COLUMN dry_run;
ALTER TABLE tasks DROP COLUMN args_redacted;
ALTER TABLE approvals DROP CONSTRAINT chk_apr_state_valid;
ALTER TABLE task_leases DROP CONSTRAINT chk_lease_active_gen;
ALTER TABLE resources DROP CONSTRAINT chk_gen_monotonic;
ALTER TABLE outbox DROP CONSTRAINT chk_outbox_dispatch;
DROP INDEX idx_outbox_reclaim;
ALTER TABLE outbox DROP COLUMN claimed_at;
ALTER TABLE outbox DROP COLUMN claim_expires_at;
ALTER TABLE outbox DROP COLUMN attempt_count;
ALTER TABLE outbox DROP COLUMN last_error;
