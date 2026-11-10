-- Forward-only repair. Do not rewrite 0001--0004 on any previously migrated DB.
ALTER TABLE outbox ADD COLUMN IF NOT EXISTS claim_token TEXT;
ALTER TABLE outbox ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_outbox_retry ON outbox(next_retry_at)
  WHERE dispatched_at IS NULL;

-- Single-user control plane: the existing domain state machine is the authority.
-- A versioned JSON checkpoint and row lock make its entire request atomic across
-- API processes. Normalized repository APIs remain separate migration adapters;
-- they are NOT a second source of truth for requests using this runtime.
CREATE TABLE runtime_state (
  id TEXT PRIMARY KEY CHECK (id = 'control-plane'),
  revision BIGINT NOT NULL DEFAULT 0 CHECK (revision >= 0),
  codec_version INTEGER NOT NULL CHECK (codec_version = 1),
  document JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (octet_length(document::text) <= 67108864)
);
