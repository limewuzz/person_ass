-- 0003：Gate B 前置整改——补齐 repository.py 引用的全部列/约束/索引
BEGIN;

-- 1) tasks 表补列（insert_task 引用 dry_run / args_redacted / origin_external_ref /
--    work_item_id / trace_id 已有；dry_run+args_redacted 此前缺列）
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS dry_run BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS args_redacted JSONB NOT NULL DEFAULT '{}'::jsonb;

-- 2) 审批有效期硬约束（consume_once 的 WHERE 由应用层+DB CHECK 双保险）
ALTER TABLE approvals DROP CONSTRAINT IF EXISTS chk_apr_state_valid;
ALTER TABLE approvals ADD CONSTRAINT chk_apr_state_valid CHECK (
  state IN ('pending','approved','rejected','expired','consumed','canceled'));

-- 3) 租约活性约束（finish/heartbeat 只能操作 released_at IS NULL 的行——DB 级保证）
ALTER TABLE task_leases DROP CONSTRAINT IF EXISTS chk_lease_active_gen;
ALTER TABLE task_leases ADD CONSTRAINT chk_lease_active_gen CHECK (
  generation >= 0 AND (released_at IS NULL OR released_at > '1970-01-01'::timestamptz));

-- 4) 资源权威写 guard：owner/kind/node 变更时 generation/write_rev 必须同语句递增
--   （0001 的触发器已覆盖 write_rev；这里补 generation 禁回退的额外 CHECK）
ALTER TABLE resources DROP CONSTRAINT IF EXISTS chk_gen_monotonic;
ALTER TABLE resources ADD CONSTRAINT chk_gen_monotonic CHECK (generation > 0);

-- 5) Outbox 可靠投递：加领取租约列（claim≠delivered；崩溃后凭 lease 过期回收重投）
ALTER TABLE outbox DROP CONSTRAINT IF EXISTS chk_outbox_dispatch;
ALTER TABLE outbox ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;
ALTER TABLE outbox ADD COLUMN IF NOT EXISTS claim_expires_at TIMESTAMPTZ;
ALTER TABLE outbox ADD COLUMN IF NOT EXISTS attempt_count INT NOT NULL DEFAULT 0;
ALTER TABLE outbox ADD COLUMN IF NOT EXISTS last_error TEXT;
ALTER TABLE outbox ADD CONSTRAINT chk_outbox_dispatch CHECK (
  (dispatched_at IS NULL) OR (dispatched_at IS NOT NULL AND claimed_at IS NOT NULL));

-- 领取过期重投索引（claim_expires_at < now() AND dispatched_at IS NULL）
CREATE INDEX IF NOT EXISTS idx_outbox_reclaim
  ON outbox(claim_expires_at) WHERE dispatched_at IS NULL;

COMMIT;
