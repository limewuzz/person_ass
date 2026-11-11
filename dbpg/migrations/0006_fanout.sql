-- V3 API checkpoint and delivery projection are written in one transaction.
ALTER TABLE runtime_state DROP CONSTRAINT runtime_state_codec_version_check;
ALTER TABLE runtime_state ADD CONSTRAINT runtime_state_codec_version_check CHECK (codec_version IN (1,2));
ALTER TABLE outbox ADD COLUMN delivery_id UUID UNIQUE;
ALTER TABLE outbox ADD COLUMN delivery_state TEXT;
