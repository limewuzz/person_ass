-- 0002：Worker 租约与 Artifact（repository.py 对应表；PG_RUNTIME NOT RUN）
BEGIN;
CREATE TABLE IF NOT EXISTS task_leases (
  id BIGSERIAL PRIMARY KEY,
  task_id UUID NOT NULL,
  worker_id TEXT NOT NULL,
  lease_token_hash TEXT NOT NULL,
  generation INT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  released_at TIMESTAMPTZ,
  expired BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS idx_leases_task_active
  ON task_leases(task_id) WHERE released_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_leases_expiry
  ON task_leases(expires_at) WHERE released_at IS NULL;

CREATE TABLE IF NOT EXISTS artifacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id UUID REFERENCES tasks(id),
  storage_system TEXT NOT NULL,
  uri TEXT NOT NULL,
  sha256 CHAR(64),
  byte_size BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());

-- 审计保留策略函数（调用方按天数传参；默认 90 天策略由运维 SOP 定）
CREATE OR REPLACE FUNCTION audit_retention_days() RETURNS int AS $$
  SELECT 90;  -- 单用户轻量控制平面默认；可由 SOP 调整后重编译
$$ LANGUAGE sql IMMUTABLE;
COMMIT;
