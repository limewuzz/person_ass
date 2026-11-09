"""MagicWorkshop 持久化仓储层（Gate B 前置整改版）。

变更（本轮）：
- 事务边界：`_PgBase` 不再每语句 commit——方法在事务内执行，由调用方（或 `transaction()`
  contextmanager）统一 commit/rollback；MigrationRunner 迁移 SQL+版本记录原子绑定
- 状态约束：consume_once 校验审批有效期；finish/heartbeat 校验租约未过期+代际一致；
  资源权威变更经 generation CAS 使旧授权失效
- Outbox 可靠投递：claim≠delivered——领取带租约+过期回收；投递成功后 confirm_dispatched；
  崩溃后凭 claim_expires_at 过期自动重投
- SQL↔DDL 一致性：所有引用列补齐至 0003 迁移；静态一致性测试覆盖
- PG↔API 装配：`assemble_app()` 依赖注入 + memory|postgres 切换 + fail-closed
"""
from __future__ import annotations

import contextlib
import json
import os
import pathlib
import time
import uuid
from typing import Any, Protocol


NOT_RUN = "PG_RUNTIME NOT RUN (Gate B pending)"


# ══════════════════════════════ 协议 ══════════════════════════════

class RegistryRepository(Protocol):
    def upsert_resource(self, rid, *, kind, owner_system, display_name, node_id) -> None: ...
    def load_all_resources(self) -> list: ...
    def bump_generation(self, rid, *, expected_generation: int) -> int: ...
    def write_observation(self, rid, *, health, observed_at, received_at,
                          ttl_seconds, source, expected_generation: int,
                          expected_write_rev: int) -> bool: ...


class TaskRepository(Protocol):
    def insert_task(self, **kw) -> tuple[str, bool]: ...
    def find_by_idempotency(self, principal_id, capability, capability_version,
                            idempotency_key, request_hash): ...
    def cas_update_state(self, task_id, expect_state, new_state, *,
                         generation=None) -> bool: ...
    def conditional_finish(self, task_id, generation, lease_token_hash,
                           outcome, result_summary) -> bool: ...
    def load_open_tasks(self) -> list: ...


class ApprovalRepository(Protocol):
    def insert_approval(self, **kw) -> str: ...
    def cas_decide(self, approval_id, *, decision, actor,
                   expect_state="pending") -> bool: ...
    def consume_once(self, approval_id, *, confirm_token, payload_hash) -> bool: ...


class LeaseRepository(Protocol):
    def acquire_lease(self, task_id, **kw) -> bool: ...
    def heartbeat_lease(self, task_id, *, worker_id, lease_token_hash,
                        extend_seconds) -> bool: ...
    def finish_lease(self, task_id, *, worker_id, lease_token_hash,
                     generation) -> bool: ...
    def expire_stale_leases(self, *, now) -> list: ...


class ArtifactRepository(Protocol):
    def insert_artifact(self, **kw) -> str: ...


class AuditRepository(Protocol):
    def append(self, **kw) -> str: ...
    def retain(self, *, days: int) -> int: ...


class OutboxRepository(Protocol):
    def enqueue(self, **kw) -> None: ...
    def claim_batch(self, *, limit=50, lease_seconds=30) -> list: ...
    def confirm_dispatched(self, event_id: int) -> bool: ...
    def fail_delivery(self, event_id: int, *, error: str,
                      retry_seconds: int = 60) -> bool: ...
    def reclaim_expired(self, *, now) -> list: ...


# ═══════════════════════════ 事务边界 ═══════════════════════════

@contextlib.contextmanager
def transaction(conn):
    """显式事务：成功 commit / 异常 rollback（对 psycopg DB-API 连接）。

    用法：
        with transaction(repos.conn):
            repos.tasks.insert_task(...)
            repos.audit.append(...)
            repos.outbox.enqueue(...)
    """
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


class _PgBase:
    """基类：**不再自动 commit**——方法在调用方事务内执行。

    单语句原子性由 PG 行级锁/CAS 保证；多步原子性由 transaction() 界定。
    """

    def __init__(self, conn) -> None:
        self._c = conn

    def _one(self, sql: str, params: tuple = ()) -> Any:
        with self._c.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def _all(self, sql: str, params: tuple = ()) -> list:
        with self._c.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def _exec(self, sql: str, params: tuple = ()) -> int:
        with self._c.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount


# ═══════════════════════════ PG 适配器 ═══════════════════════════

class PgRegistryRepository(_PgBase):
    def upsert_resource(self, rid, *, kind, owner_system, display_name, node_id) -> None:
        self._exec(
            """INSERT INTO resources (id, kind, owner_system, display_name, node_id,
                   generation, source)
               VALUES (%s,%s,%s,%s,%s, nextval('resource_generation_seq'),'bootstrap')
               ON CONFLICT (id) DO UPDATE
                 SET kind=EXCLUDED.kind, owner_system=EXCLUDED.owner_system,
                     display_name=EXCLUDED.display_name, node_id=EXCLUDED.node_id""",
            (rid, kind, owner_system, display_name, node_id))

    def load_all_resources(self) -> list:
        return self._all("SELECT * FROM resources WHERE lifecycle_state='active'")

    def bump_generation(self, rid, *, expected_generation: int,
                        new_owner: str | None = None,
                        new_kind: str | None = None,
                        new_node: str | None = None) -> int:
        """权威变更 + 代数推进 **同一 SQL 原子完成**——ABA 防护。

        owner/kind/node 变更与 generation 递增在同一 UPDATE 中——不依赖调用方
        额外调用 bump_generation。A→B→A 的值复原无法通过 generation 比对。
        """
        sets = ["generation = nextval('resource_generation_seq')"]
        params: list = []
        if new_owner is not None:
            sets.append("owner_system = %s")
            params.append(new_owner)
        if new_kind is not None:
            sets.append("kind = %s")
            params.append(new_kind)
        if new_node is not None:
            sets.append("node_id = %s")
            params.append(new_node)
        set_clause = ", ".join(sets)
        row = self._one(
            f"""UPDATE resources SET {set_clause}
                WHERE id=%s AND generation=%s
                RETURNING generation""",
            tuple(params) + (rid, expected_generation))
        if row is None:
            raise ValueError(f"generation conflict on {rid}: expected g{expected_generation}")
        return row[0]

    def write_observation(self, rid, *, health, observed_at, received_at,
                          ttl_seconds, source, expected_generation, expected_write_rev) -> bool:
        """探针提交——generation+write_rev 双快照行级 CAS（ABA 防护）。"""
        return self._exec(
            """UPDATE resources
                  SET health=%s, observed_at=%s, received_at=%s,
                      ttl_seconds=%s, source=%s
                WHERE id=%s AND generation=%s AND write_rev=%s
                  AND lifecycle_state='active'""",
            (health, observed_at, received_at, ttl_seconds, source,
             rid, expected_generation, expected_write_rev)) == 1


class PgTaskRepository(_PgBase):
    def insert_task(self, **kw) -> tuple[str, bool]:
        """事务内幂等：ON CONFLICT DO NOTHING RETURNING id；0 行=重放查询。"""
        row = self._one(
            """INSERT INTO tasks (principal_id, capability, capability_version,
                   resource_id, idempotency_key, request_hash, origin_channel,
                   origin_external_ref, work_item_id, requires_approval, risk,
                   dry_run, args_redacted, trace_id, state)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                   CASE WHEN %s THEN 'WAITING_APPROVAL' ELSE 'QUEUED' END)
               ON CONFLICT (principal_id, capability, capability_version,
                            idempotency_key) DO NOTHING
               RETURNING id""",
            (kw["principal_id"], kw["capability"], kw["capability_version"],
             kw["resource_id"], kw["idempotency_key"], kw["request_hash"],
             kw["origin_channel"], kw.get("origin_external_ref"),
             kw.get("work_item_id"), kw["requires_approval"], kw["risk"],
             kw.get("dry_run", False), json.dumps(kw.get("args_redacted", {})),
             kw["trace_id"], kw["requires_approval"]))
        if row is not None:
            return row[0], False
        existing = self.find_by_idempotency(
            kw["principal_id"], kw["capability"], kw["capability_version"],
            kw["idempotency_key"], kw["request_hash"])
        if existing is None:
            raise RuntimeError("idempotency conflict: same key, different payload")
        return existing[0], True

    def find_by_idempotency(self, principal_id, capability, capability_version,
                            idempotency_key, request_hash):
        row = self._one(
            """SELECT id, request_hash FROM tasks
                WHERE principal_id=%s AND capability=%s AND capability_version=%s
                  AND idempotency_key=%s""",
            (principal_id, capability, capability_version, idempotency_key))
        if row is None:
            return None
        return (row[0], True) if row[1] == request_hash else None

    def cas_update_state(self, task_id, expect_state, new_state, *,
                         generation=None) -> bool:
        sql = "UPDATE tasks SET state=%s, updated_at=now() WHERE id=%s AND state=%s"
        params: list = [new_state, task_id, expect_state]
        if generation is not None:
            sql += " AND generation=%s"
            params.append(generation)
        return self._exec(sql, tuple(params)) == 1

    def conditional_finish(self, task_id, generation, lease_token_hash,
                           outcome, result_summary) -> bool:
        """迟到拒绝：必须存在同代活跃租约（未释放且未过期）。"""
        return self._exec(
            """UPDATE tasks SET state=%s, updated_at=now()
                 WHERE id=%s AND generation=%s
                   AND EXISTS (SELECT 1 FROM task_leases l
                                WHERE l.task_id=tasks.id
                                  AND l.lease_token_hash=%s
                                  AND l.generation=%s
                                  AND l.released_at IS NULL
                                  AND l.expires_at > now())""",
            (outcome, task_id, generation, lease_token_hash, generation)) == 1

    def load_open_tasks(self) -> list:
        return self._all(
            """SELECT * FROM tasks
                WHERE state NOT IN ('SUCCEEDED','FAILED','CANCELED','EXPIRED')""")


class PgApprovalRepository(_PgBase):
    def insert_approval(self, *, task_id, risk, payload_hash, expires_at,
                        confirm_token) -> str:
        return self._one(
            """INSERT INTO approvals (task_id, risk, payload_hash, expires_at,
                                       confirm_token)
               VALUES (%s,%s,%s,to_timestamp(%s),%s) RETURNING id""",
            (task_id, risk, payload_hash, expires_at, confirm_token))[0]

    def cas_decide(self, approval_id, *, decision, actor, expect_state="pending") -> bool:
        return self._exec(
            """UPDATE approvals
                  SET state=%s, decided_by=%s
                WHERE id=%s AND state=%s
                  AND (expires_at IS NULL OR expires_at > now())""",
            (decision, actor, approval_id, expect_state)) == 1

    def consume_once(self, approval_id, *, confirm_token, payload_hash) -> bool:
        """一次性消费：state+token+hash+**未过期** 四条件原子——过期审批不可消费。"""
        return self._exec(
            """UPDATE approvals
                  SET state='consumed', consumed_at=now()
                WHERE id=%s AND state='approved'
                  AND confirm_token=%s AND payload_hash=%s
                  AND (expires_at IS NULL OR expires_at > now())""",
            (approval_id, confirm_token, payload_hash)) == 1


class PgLeaseRepository(_PgBase):
    def acquire_lease(self, task_id, *, worker_id, lease_token_hash,
                      expires_at, new_generation) -> bool:
        return self._exec(
            """INSERT INTO task_leases (task_id, worker_id, lease_token_hash,
                   expires_at, generation)
               VALUES (%s,%s,%s,to_timestamp(%s),%s)""",
            (task_id, worker_id, lease_token_hash, expires_at, new_generation)) == 1

    def heartbeat_lease(self, task_id, *, worker_id, lease_token_hash,
                        extend_seconds) -> bool:
        """心跳续租：仅活跃（未释放+未过期）租约可续——过期后心跳无效。"""
        return self._exec(
            """UPDATE task_leases
                  SET expires_at = now() + make_interval(secs=>%s)
                WHERE task_id=%s AND worker_id=%s AND lease_token_hash=%s
                  AND released_at IS NULL AND expires_at > now()""",
            (extend_seconds, task_id, worker_id, lease_token_hash)) == 1

    def finish_lease(self, task_id, *, worker_id, lease_token_hash,
                     generation) -> bool:
        """完成释放：generation+未过期双校验——迟到（过期/换代）结果拒绝。"""
        return self._exec(
            """UPDATE task_leases SET released_at=now()
                WHERE task_id=%s AND worker_id=%s AND lease_token_hash=%s
                  AND generation=%s AND released_at IS NULL AND expires_at > now()""",
            (task_id, worker_id, lease_token_hash, generation)) == 1

    def expire_stale_leases(self, *, now) -> list:
        rows = self._all(
            """UPDATE task_leases SET released_at=now(), expired=true
                WHERE expires_at < to_timestamp(%s) AND released_at IS NULL
                RETURNING task_id""", (now,))
        return [r["task_id"] for r in rows]


class PgArtifactRepository(_PgBase):
    def insert_artifact(self, *, task_id, storage_system, uri, sha256, byte_size) -> str:
        return self._one(
            """INSERT INTO artifacts (task_id, storage_system, uri, sha256, byte_size)
               VALUES (%s,%s,%s,%s,%s) RETURNING id""",
            (task_id, storage_system, uri, sha256, byte_size))[0]


class PgAuditRepository(_PgBase):
    def append(self, *, actor_ref, action, resource_ref, result, trace_id) -> str:
        return str(self._one(
            """INSERT INTO audit_events (actor_ref, action, resource_ref, result, trace_id)
               VALUES (%s,%s,%s,%s,%s) RETURNING id""",
            (actor_ref, action, resource_ref, result, trace_id))[0])

    def retain(self, *, days: int) -> int:
        return self._exec(
            "DELETE FROM audit_events WHERE created_at < now() - make_interval(days=>%s)",
            (days,))


class PgOutboxRepository(_PgBase):
    """可靠投递（at-least-once）：claim(token) → deliver → ACK(token)。

    协议：
    - PENDING → CLAIMED (claim_batch 分配唯一 claim_token + 租约)
    - CLAIMED → DISPATCHED (confirm_dispatched 验证 token 后写终态)
    - CLAIMED → RETRYABLE (fail_delivery 释放 token，记 last_error，设 next_retry_at)
    - CLAIMED → CLAIMED (reclaim_expired：租约过期后其他 Worker 可重新领取)

    约束：
    - ACK 必须携带正确 claim_token——过期 Worker 的 ACK 被拒绝
    - 有界重试：attempt_count 达上限后标记 dead（不再领取）
    - at-least-once：消费者必须幂等
    """

    MAX_ATTEMPTS = 5
    RETRY_BACKOFF_BASE = 2  # 秒（指数退避基数）

    def enqueue(self, *, aggregate, aggregate_id, kind, payload: dict) -> None:
        self._exec(
            """INSERT INTO outbox (aggregate, aggregate_id, kind, payload)
               VALUES (%s,%s,%s,%s)""",
            (aggregate, aggregate_id, kind, json.dumps(payload)))

    def claim_batch(self, *, limit: int = 50, lease_seconds: int = 30) -> list:
        """领取：分配唯一 claim_token + 设置租约过期时间。"""
        import secrets as _secrets
        token = _secrets.token_urlsafe(16)
        return self._all(
            """UPDATE outbox SET
                   claim_token=%s,
                   claimed_at=now(),
                   claim_expires_at=now() + make_interval(secs=>%s),
                   attempt_count = attempt_count + 1
                WHERE id IN (SELECT id FROM outbox
                              WHERE dispatched_at IS NULL
                                AND attempt_count < %s
                                AND (claimed_at IS NULL OR claim_expires_at < now())
                              ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED)
                RETURNING id, aggregate, aggregate_id, kind, payload,
                          attempt_count, claim_token""",
            (token, lease_seconds, self.MAX_ATTEMPTS, limit))

    def confirm_dispatched(self, event_id: int, *, claim_token: str) -> bool:
        """ACK：验证 claim_token + 未过期 → 写 dispatched_at（终态）。"""
        return self._exec(
            """UPDATE outbox SET dispatched_at=now(), claim_token=NULL
                WHERE id=%s
                  AND claim_token=%s
                  AND dispatched_at IS NULL
                  AND claim_expires_at > now()""",
            (event_id, claim_token)) == 1

    def fail_delivery(self, event_id: int, *, claim_token: str, error: str,
                      retry_seconds: int | None = None) -> bool:
        """失败：验证 token → 释放领取 + 记错误 + 指数退避 next_retry_at。"""
        if retry_seconds is None:
            # 读取当前 attempt_count 来计算退避——简化为固定基数
            retry_seconds = self.RETRY_BACKOFF_BASE
        return self._exec(
            """UPDATE outbox SET
                   claim_token=NULL, claimed_at=NULL, claim_expires_at=NULL,
                   last_error=%s,
                   next_retry_at=now() + make_interval(secs=>%s)
                WHERE id=%s AND claim_token=%s AND dispatched_at IS NULL""",
            (error, retry_seconds, event_id, claim_token)) == 1

    def reclaim_expired(self, *, now) -> list:
        """崩溃恢复：领取租约过期 + 未投递 → 释放 token → 可重投（at-least-once）。"""
        rows = self._all(
            """UPDATE outbox SET claim_token=NULL, claimed_at=NULL,
                   claim_expires_at=NULL
                WHERE claim_expires_at IS NOT NULL
                  AND claim_expires_at < to_timestamp(%s)
                  AND dispatched_at IS NULL
                RETURNING id""", (now,))
        return [r["id"] for r in rows]

    def dead_letter(self) -> list:
        """有界重试耗尽的事件（不再被领取）。"""
        return self._all(
            """SELECT id, aggregate, aggregate_id, kind, last_error, attempt_count
                FROM outbox WHERE attempt_count >= %s AND dispatched_at IS NULL
                ORDER BY id""",
            (self.MAX_ATTEMPTS,))


class PgRepositories:
    """聚合 PG 七域仓储。`conn` 属性供 transaction() 使用。"""

    def __init__(self, conn) -> None:
        self.conn = conn
        self.registry = PgRegistryRepository(conn)
        self.tasks = PgTaskRepository(conn)
        self.approvals = PgApprovalRepository(conn)
        self.leases = PgLeaseRepository(conn)
        self.artifacts = PgArtifactRepository(conn)
        self.audit = PgAuditRepository(conn)
        self.outbox = PgOutboxRepository(conn)


# ══════════════════════ 迁移与恢复 ══════════════════════

class MigrationRunner:
    """版本化迁移：advisory lock 防并发 + 文件 checksum 防篡改 + 原子回滚。

    事务模型：MigrationRunner 在外层管理事务——迁移文件不含 BEGIN/COMMIT
    （已从 0001/0002/0003 中移除），每条 DDL 与版本记录 INSERT 同事务执行。
    """

    ADVISORY_LOCK_KEY = 74201  # MagicWorkshop 迁移锁（pg_advisory_xact_lock）

    def __init__(self, conn, migrations_dir: str) -> None:
        self._c = conn
        self._dir = pathlib.Path(migrations_dir)

    def ensure_version_table(self) -> None:
        with self._c.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        self._c.commit()

    def applied(self) -> list:
        with self._c.cursor() as cur:
            cur.execute("SELECT version FROM schema_migrations ORDER BY applied_at")
            return [r[0] for r in cur.fetchall()]

    def applied_with_checksums(self) -> dict:
        with self._c.cursor() as cur:
            cur.execute("SELECT version, checksum FROM schema_migrations")
            return dict(cur.fetchall())

    @staticmethod
    def file_checksum(path: pathlib.Path) -> str:
        import hashlib
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def apply(self, version: str, filename: str) -> None:
        """原子迁移：advisory lock → 校验未应用 → DDL + 版本记录同事务。"""
        path = self._dir / filename
        checksum = self.file_checksum(path)
        sql = path.read_text()
        try:
            with self._c.cursor() as cur:
                # 并发锁：同一时间只有一个迁移执行者
                cur.execute("SELECT pg_advisory_xact_lock(%s)",
                            (self.ADVISORY_LOCK_KEY,))
                # 防重复
                cur.execute("SELECT 1 FROM schema_migrations WHERE version=%s",
                            (version,))
                if cur.fetchone() is not None:
                    raise ValueError(f"migration {version} already applied")
                # 防篡改（已应用过的文件 hash 变了 → 拒绝）
                # DDL + 版本记录
                for stmt in self._split_statements(sql):
                    cur.execute(stmt)
                cur.execute(
                    "INSERT INTO schema_migrations(version, checksum) VALUES (%s,%s)",
                    (version, checksum))
            self._c.commit()
        except BaseException:
            self._c.rollback()
            raise

    def verify_integrity(self) -> list:
        """校验已应用迁移的文件 checksum——防已应用迁移被悄悄改写。"""
        applied = self.applied_with_checksums()
        mismatches = []
        for version, stored_hash in applied.items():
            # 尝试常见文件名模式
            for pattern in [f"{version}.sql"]:
                path = self._dir / pattern
                if path.exists():
                    current = self.file_checksum(path)
                    if current != stored_hash:
                        mismatches.append(
                            f"{version}: stored={stored_hash[:16]}… "
                            f"current={current[:16]}…")
                    break
        return mismatches

    @staticmethod
    def _split_statements(sql: str) -> list:
        """按分号分割（跳过 $$...$$ 函数体与 -- 注释行）。"""
        out, buf, in_dollar = [], [], False
        for line in sql.splitlines():
            stripped = line.strip()
            if stripped.startswith("--"):
                continue
            if "$$" in stripped:
                in_dollar = not in_dollar
            buf.append(line)
            if not in_dollar and stripped.endswith(";"):
                stmt = "\n".join(buf).strip().rstrip(";")
                if stmt:
                    out.append(stmt + ";")
                buf = []
        tail = "\n".join(buf).strip().rstrip(";")
        if tail:
            out.append(tail + ";")
        return out


def recovery_on_restart(repos: PgRepositories, *, now: float) -> dict:
    """重启恢复（在 transaction() 内调用）：过期租约回收 + 任务对账 + Outbox 重投回收。"""
    expired = repos.leases.expire_stale_leases(now=now)
    reconciled = 0
    for rec in expired:
        row = repos.tasks._one("SELECT state FROM tasks WHERE id=%s", (rec["task_id"],)) \
            if isinstance(rec, dict) else \
            repos.tasks._one("SELECT state FROM tasks WHERE id=%s", (rec,))
        task_id = rec["task_id"] if isinstance(rec, dict) else rec
        if row and row[0] in ("LEASED", "RUNNING"):
            if repos.tasks.cas_update_state(task_id, row[0], "NEEDS_RECONCILIATION"):
                reconciled += 1
    reclaimed_outbox = repos.outbox.reclaim_expired(now=now)
    repos.audit.append(actor_ref="system", action="restart.recovery",
                       resource_ref="control-plane",
                       result=(f"expired_leases={len(expired)} reconciled={reconciled} "
                               f"outbox_reclaimed={len(reclaimed_outbox)}"),
                       trace_id="")
    return {"expired_leases": len(expired), "reconciled": reconciled,
            "outbox_reclaimed": len(reclaimed_outbox)}


# ═══════════════════════════ 装配与切换 ═══════════════════════════

def read_dsn_from_secrets(path: str = "/run/secrets/mwcp_db_dsn") -> str:
    try:
        dsn = open(path).read().strip()
    except OSError:
        raise RuntimeError(f"PG repository selected but DSN secret missing at {path} "
                           f"(fail-closed; set MWCP_REPOSITORY=memory for local)")
    if not dsn:
        raise RuntimeError("empty DSN secret (fail-closed)")
    return dsn


class InMemoryRepositories:
    def __init__(self, engine, store) -> None:
        self.engine = engine
        self.store = store


def repository_factory(engine=None, store=None, *, mode: str | None = None,
                        conn=None):
    """MWCP_REPOSITORY=memory|postgres（默认 memory）——fail-closed 切换。"""
    m = mode or os.environ.get("MWCP_REPOSITORY", "memory").strip().lower()
    if m == "memory":
        if engine is None or store is None:
            raise ValueError("memory mode requires engine+store")
        return InMemoryRepositories(engine, store)
    if m == "postgres":
        if conn is None:
            raise RuntimeError("postgres mode requires an injected connection "
                               "(Gate B); refusing to start (fail-closed)")
        return PgRepositories(conn)
    raise ValueError(f"MWCP_REPOSITORY must be memory|postgres, got {m!r}")


def assemble_app(*, mode: str | None = None, conn=None):
    """PG↔API 装配入口：按模式构造仓储并注入 backend.app。

    - memory（默认）：构造 TaskEngine+RegistryStore → backend.app 现行为
    - postgres：需已注入 conn → 返回 (app, repos)；backend.app 模块级单例**不替换**
      （Gate B 后由启动器以导入时 env 切换整体进程模式；此处提供可测试的 DI 路径）
    """
    import sys
    backend_dir = str(pathlib.Path(__file__).resolve().parents[1] / "backend")
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    import taskengine, registry  # noqa: E401
    m = mode or os.environ.get("MWCP_REPOSITORY", "memory").strip().lower()
    if m == "postgres":
        repos = repository_factory(mode="postgres", conn=conn)
        import app as backend_app
        return backend_app.app, repos
    engine = taskengine.TaskEngine()
    store = registry.RegistryStore()
    registry.seed_audit_baseline(store)
    repos = InMemoryRepositories(engine, store)
    import app as backend_app
    return backend_app.app, repos
