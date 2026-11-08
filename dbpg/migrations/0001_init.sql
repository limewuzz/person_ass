-- MagicWorkshop Control Plane 0001（PG v5 起点的完整 DDL；PG_RUNTIME NOT RUN）
-- 对应 PRD §E：唯一约束=幂等/审批/出队盒；generation 单调（序列+触发器禁回退）
BEGIN;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 资源代数序列（删除重建不复用；进程重启持久）
CREATE SEQUENCE resource_generation_seq START 1;

CREATE TABLE principals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  provider TEXT NOT NULL, external_subject TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '', role TEXT NOT NULL,
  disabled_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(provider, external_subject));

CREATE TABLE resources (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL, owner_system TEXT NOT NULL, display_name TEXT NOT NULL,
  node_id TEXT, generation BIGINT NOT NULL DEFAULT nextval('resource_generation_seq'),
  lifecycle_state TEXT NOT NULL DEFAULT 'active',
  health TEXT NOT NULL DEFAULT 'unknown',
  observed_at TIMESTAMPTZ, received_at TIMESTAMPTZ, ttl_seconds INT,
  source TEXT NOT NULL DEFAULT 'audit_baseline',
  write_rev BIGINT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (generation > 0), CHECK (write_rev >= 0));
CREATE INDEX idx_resources_gen ON resources(id, generation);

-- 权威写只经受控路径：触发器保证 kind/owner/node 变更必须同语句递增 write_rev
CREATE OR REPLACE FUNCTION resources_write_rev_guard() RETURNS trigger AS $$
BEGIN
  IF NEW.kind IS DISTINCT FROM OLD.kind OR NEW.owner_system IS DISTINCT FROM OLD.owner_system
     OR NEW.node_id IS DISTINCT FROM OLD.node_id THEN
    NEW.write_rev := OLD.write_rev + 1;
  END IF;
  NEW.generation := GREATEST(NEW.generation, OLD.generation);  -- 禁回退
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_resources_rev BEFORE UPDATE ON resources
  FOR EACH ROW EXECUTE FUNCTION resources_write_rev_guard();

-- 探针目标授权（6 元组 + resource 绑定；版本 CAS + 审计在应用层/触发器双层）
CREATE TABLE approved_probe_targets (
  resource_id TEXT NOT NULL REFERENCES resources(id),
  capability TEXT NOT NULL, scheme TEXT, host TEXT NOT NULL, port INT, path TEXT,
  query_fingerprint TEXT, kind TEXT NOT NULL, node_id TEXT,
  resource_owner TEXT NOT NULL, resource_generation BIGINT NOT NULL,
  version INT NOT NULL DEFAULT 1, enabled BOOLEAN NOT NULL DEFAULT TRUE,
  owner TEXT NOT NULL DEFAULT '', approved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(resource_id));
CREATE TABLE target_change_log (
  id BIGSERIAL PRIMARY KEY, target_id TEXT NOT NULL, action TEXT NOT NULL,
  from_version INT NOT NULL, to_version INT NOT NULL,
  endpoint_display TEXT NOT NULL,  -- 脱敏展示（无原始 path/query）
  kind TEXT, node_id TEXT, owner TEXT, changed_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE work_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
  kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
  created_by TEXT NOT NULL, source_system TEXT, source_external_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(source_system, source_external_id));

CREATE TABLE tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  work_item_id UUID REFERENCES work_items(id),
  principal_id TEXT NOT NULL,
  capability TEXT NOT NULL, capability_version INT NOT NULL,
  resource_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL CHECK(length(idempotency_key) BETWEEN 12 AND 256),
  request_hash CHAR(64) NOT NULL,
  origin_channel TEXT NOT NULL, origin_external_ref TEXT,
  state TEXT NOT NULL DEFAULT 'DRAFT',
  generation INT NOT NULL DEFAULT 0,
  trace_id UUID NOT NULL DEFAULT gen_random_uuid(),
  requires_approval BOOLEAN NOT NULL DEFAULT FALSE, risk TEXT NOT NULL DEFAULT 'READ',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(principal_id, capability, capability_version, idempotency_key));  -- 幂等唯一索引
CREATE INDEX idx_tasks_state ON tasks(state, created_at);

CREATE TABLE task_events (
  id BIGSERIAL PRIMARY KEY, task_id UUID NOT NULL REFERENCES tasks(id),
  sequence INT NOT NULL, kind TEXT NOT NULL, occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  summary TEXT NOT NULL, trace_id UUID NOT NULL,
  UNIQUE(task_id, sequence));

CREATE TABLE task_attempts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id UUID NOT NULL REFERENCES tasks(id),
  worker_id TEXT NOT NULL, generation INT NOT NULL,
  started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, outcome TEXT, result_summary TEXT);

CREATE TABLE approvals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id UUID NOT NULL REFERENCES tasks(id),
  risk TEXT NOT NULL, payload_hash CHAR(64) NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL, consumed_at TIMESTAMPTZ,
  confirm_token TEXT NOT NULL, decided_by TEXT,
  CHECK (state IN ('pending','approved','rejected','expired','consumed','canceled')));
-- 一次性消费的原子更新（应用层以此 CAS）：
--   UPDATE approvals SET state='consumed', consumed_at=now()
--    WHERE id=$1 AND state='approved' AND confirm_token=$2 AND payload_hash=$3
--    RETURNING …（0 行=已消费/篡改/过期）

CREATE TABLE audit_events (
  id BIGSERIAL PRIMARY KEY, actor_ref TEXT NOT NULL, action TEXT NOT NULL,
  resource_ref TEXT NOT NULL, result TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), trace_id UUID);
CREATE INDEX idx_audit_created ON audit_events(created_at DESC);

-- Transactional outbox（PRD §C：最终一致；本地 mock 以同一语义驱动）
CREATE TABLE outbox (
  id BIGSERIAL PRIMARY KEY, aggregate TEXT NOT NULL, aggregate_id TEXT NOT NULL,
  kind TEXT NOT NULL, payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  dispatched_at TIMESTAMPTZ,
  UNIQUE(aggregate, aggregate_id, kind, created_at));  -- inbox 去重同表反向用途
COMMIT;
