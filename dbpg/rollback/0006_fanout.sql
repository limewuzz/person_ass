-- DESTRUCTIVE isolated experiments only; reject rollback while V3 state exists.
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM runtime_state WHERE codec_version=2) THEN
  RAISE EXCEPTION 'Restore a verified V2 backup before downgrading the codec';
 END IF;
END $$;
ALTER TABLE outbox DROP COLUMN delivery_state;
ALTER TABLE outbox DROP COLUMN delivery_id;
ALTER TABLE runtime_state DROP CONSTRAINT runtime_state_codec_version_check;
ALTER TABLE runtime_state ADD CONSTRAINT runtime_state_codec_version_check CHECK(codec_version=1);
