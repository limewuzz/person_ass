-- DESTRUCTIVE: disposable Gate B database only; stop API first.
DROP TABLE runtime_state;
DROP INDEX idx_outbox_retry;
ALTER TABLE outbox DROP COLUMN next_retry_at;
ALTER TABLE outbox DROP COLUMN claim_token;
