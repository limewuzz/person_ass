"""MagicWorkshop 持久化仓储层（PG 适配器完整实现；连接真实库仍需 Gate B 授权）。

设计分层：
- 协议（Protocol）：七域边界（Registry/Task/Approval/Lease/Artifact/Audit/Outbox）
- InMemory*：委托 backend 内存实现（本地 RC 运行时）
- Pg*：完整参数化 SQL 实现——**连接由外部注入**（DSN 从 /run/secrets/mwcp_db_dsn 读取，
  绝不入 env/argv/git）；本仓库不 import 任何 DB 驱动，驱动在部署 Gate 后由调用方安装注入
- 切换：MWCP_REPOSITORY=memory|postgres（factory见底部）；postgres 模式 fail-closed：
  无 DSN 文件即拒绝启动
- 离线测试：dbpg/tests/ 用假连接（FakeCursor）断言 SQL 文本/参数/CAS 语义/事务边界，
  不连任何真实库；真实库验证属于 Gate B（隔离实验，另批）
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
import uuid
from typing import Any, Protocol

NOT_RUN = "PG_RUNTIME NOT RUN (Gate B pending)"


# ══════════════════════════════ 协议 ══════════════════════════════

class RegistryRepository(Protocol):
    def upsert_resource(self, rid, *, kind, owner_system, display_name, node_id) -> None: ...
    def load_all_resources(self) -> list: ...
    def bump_generation(self, rid, *, expected_generation: int) -> int:
        """UPDATE resources SET generation=nextval(seq) WHERE id=:rid AND generation=:expected
        RETURNING generation —— ABA 防护（值复原无法通过代数比对）。"""
    def write_observation(self, rid, *, health, observed_at, received_at,
                          ttl_seconds, source, expected_generation: int,
                          expected_write_rev: int) -> bool: ...


class TaskRepository(Protocol):
    def insert_task(self, *, principal_id: str, capability: str, capability_version: int,
                    resource_id: str, idempotency_key: str, request_hash: str,
                    origin_channel: str, origin_external_ref, work_item_id,
                    requires_approval: bool, risk: str, dry_run: bool,
                    args_redacted: dict, trace_id: str) -> tuple[str, bool]:
        """INSERT ... ON CONFLICT (principal_id, capability, capability_version,
        idempotency_key) DO NOTHING RETURNING id —— 事务内幂等；replayed=bool。"""
    def find_by_idempotency(self, principal_id, capability, capability_version,
                            idempotency_key, request_hash) -> tuple[str, bool] | None: ...
    def cas_update_state(self, task_id: str, expect_state: str, new_state: str,
                         *, generation: int | None = None) -> bool:
        """UPDATE tasks SET state=:new, updated_at=now()
        WHERE id=:id AND state=:expect [AND generation=:g] RETURNING 1。"""
    def conditional_finish(self, task_id: str, generation: int, lease_token_hash: str,
                           outcome: str, result_summary) -> bool: ...
    def load_open_tasks(self) -> list:
        """重启恢复：非终态任务（含 LEASED/RUNNING 过期 → NEEDS_RECONCILIATION）。"""


class ApprovalRepository(Protocol):
    def insert_approval(self, *, task_id, risk, payload_hash, expires_at,
                        confirm_token) -> str: ...
    def cas_decide(self, approval_id, *, decision: str, actor: str,
                   expect_state: str = "pending") -> bool: ...
    def consume_once(self, approval_id, *, confirm_token: str, payload_hash: str) -> bool:
        """一次性消费：UPDATE approvals SET state='consumed', consumed_at=now()
        WHERE id=:id AND state='approved' AND confirm_token=:t AND payload_hash=:h
        RETURNING 1 —— 0 行=已消费/篡改/过期（PG 原子，无 check-then-write 竞态）。"""


class LeaseRepository(Protocol):
    def acquire_lease(self, task_id, *, worker_id: str, lease_token_hash: str,
                      expires_at: float, new_generation: int) -> bool: ...
    def heartbeat_lease(self, task_id, *, worker_id, lease_token_hash,
                        extend_seconds: int) -> bool: ...
    def finish_lease(self, task_id, *, worker_id, lease_token_hash,
                     generation: int) -> bool:
        """UPDATE task_leases SET released_at=now() WHERE ... AND generation=:g
        AND released_at IS NULL RETURNING —— 迟到结果（已释放/换代）拒绝。"""
    def expire_stale_leases(self, *, now: float) -> list:
        """重启/对账：回收 expires_at < now 且未释放的租约 → 任务 NEEDS_RECONCILIATION。"""


class ArtifactRepository(Protocol):
    def insert_artifact(self, *, task_id, storage_system, uri, sha256, byte_size) -> str: ...


class AuditRepository(Protocol):
    def append(self, *, actor_ref, action, resource_ref, result, trace_id) -> str: ...
    def retain(self, *, days: int) -> int: ...


class OutboxRepository(Protocol):
    def enqueue(self, *, aggregate, aggregate_id, kind, payload: dict) -> None: ...
    def claim_batch(self, *, limit: int = 50) -> list: ...
    def mark_dispatched(self, event_id: int) -> None: ...


# ════════════════════════ InMemory（委托 backend 实现）════════════════════════

class InMemoryRepositories:
    """聚合本地内存实现（TaskEngine/RegistryStore 等）；工厂注入 backend 模块。"""

    def __init__(self, engine, store) -> None:
        self.engine = engine      # backend.taskengine.TaskEngine
        self.store = store        # backend.registry.RegistryStore


# ═══════════════════════════ PG 适配器 ═══════════════════════════
# 约定：conn 为 DB-API 2.0 / psycopg 风格连接（contextmanager 事务）。
# 全部方法单语句原子（行级锁/CAS），多步流程由调用方在事务里组合。

class _PgBase:
    def __init__(self, conn) -> None:
        self._c = conn

    def _one(self, sql: str, params: tuple = ()) -> Any:
        with self._c.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        self._c.commit()
        return row

    def _exec(self, sql: str, params: tuple = ()) -> int:
        with self._c.cursor() as cur:
            cur.execute(sql, params)
            n = cur.rowcount
        self._c.commit()
        return n


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
        with self._c.cursor() as cur:
            cur.execute("SELECT * FROM resources WHERE lifecycle_state='active'")
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def bump_generation(self, rid, *, expected_generation: int) -> int:
        row = self._one(
            """UPDATE resources
                  SET generation = nextval('resource_generation_seq')
                WHERE id=%s AND generation=%s
                RETURNING generation""",
            (rid, expected_generation))
        if row is None:
            raise ValueError(f"generation conflict on {rid}: "
                             f"expected g{expected_generation}")
        return row[0]

    def write_observation(self, rid, *, health, observed_at, received_at,
                          ttl_seconds, source, expected_generation: int,
                          expected_write_rev: int) -> bool:
        """探针提交（行级 CAS：generation+write_rev 双比对——ABA 复原无法通过）。"""
        n = self._exec(
            """UPDATE resources
                  SET health=%s, observed_at=%s, received_at=%s,
                      ttl_seconds=%s, source=%s
                WHERE id=%s AND generation=%s AND write_rev=%s
                  AND lifecycle_state='active'""",
            (health, observed_at, received_at, ttl_seconds, source,
             rid, expected_generation, expected_write_rev))
        return n == 1


class PgTaskRepository(_PgBase):
    def insert_task(self, **kw) -> tuple[str, bool]:
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
        if row[1] != request_hash:
            return None  # 调用方以 None+既有键 判定 409
        return row[0], True

    def cas_update_state(self, task_id, expect_state, new_state, *,
                         generation=None) -> bool:
        if generation is not None:
            n = self._exec(
                """UPDATE tasks SET state=%s, updated_at=now()
                     WHERE id=%s AND state=%s AND generation=%s""",
                (new_state, task_id, expect_state, generation))
        else:
            n = self._exec(
                """UPDATE tasks SET state=%s, updated_at=now()
                     WHERE id=%s AND state=%s""",
                (new_state, task_id, expect_state))
        return n == 1

    def conditional_finish(self, task_id, generation, lease_token_hash,
                           outcome, result_summary) -> bool:
        n = self._exec(
            """UPDATE tasks SET state=%s, updated_at=now()
                 WHERE id=%s AND generation=%s
                   AND EXISTS (SELECT 1 FROM task_leases l
                                WHERE l.task_id=tasks.id
                                  AND l.lease_token_hash=%s
                                  AND l.released_at IS NULL)""",
            (outcome, task_id, generation, lease_token_hash))
        return n == 1

    def load_open_tasks(self) -> list:
        with self._c.cursor() as cur:
            cur.execute(
                """SELECT * FROM tasks
                    WHERE state NOT IN ('SUCCEEDED','FAILED','CANCELED','EXPIRED')""")
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


class PgApprovalRepository(_PgBase):
    def insert_approval(self, *, task_id, risk, payload_hash, expires_at,
                        confirm_token) -> str:
        row = self._one(
            """INSERT INTO approvals (task_id, risk, payload_hash, expires_at,
                                       confirm_token)
               VALUES (%s,%s,%s,to_timestamp(%s),%s) RETURNING id""",
            (task_id, risk, payload_hash, expires_at, confirm_token))
        return row[0]

    def cas_decide(self, approval_id, *, decision, actor, expect_state="pending") -> bool:
        n = self._exec(
            """UPDATE approvals
                  SET state=%s, decided_by=%s
                WHERE id=%s AND state=%s
                  AND (expires_at IS NULL OR expires_at > now())""",
            (decision, actor, approval_id, expect_state))
        return n == 1

    def consume_once(self, approval_id, *, confirm_token, payload_hash) -> bool:
        n = self._exec(
            """UPDATE approvals
                  SET state='consumed', consumed_at=now()
                WHERE id=%s AND state='approved'
                  AND confirm_token=%s AND payload_hash=%s""",
            (approval_id, confirm_token, payload_hash))
        return n == 1


class PgLeaseRepository(_PgBase):
    def acquire_lease(self, task_id, *, worker_id, lease_token_hash,
                      expires_at, new_generation) -> bool:
        n = self._exec(
            """INSERT INTO task_leases (task_id, worker_id, lease_token_hash,
                   expires_at, generation)
               VALUES (%s,%s,%s,to_timestamp(%s),%s)""",
            (task_id, worker_id, lease_token_hash, expires_at, new_generation))
        return n == 1

    def heartbeat_lease(self, task_id, *, worker_id, lease_token_hash,
                        extend_seconds) -> bool:
        n = self._exec(
            """UPDATE task_leases
                  SET expires_at = greatest(expires_at, now() + make_interval(secs=>%s))
                WHERE task_id=%s AND worker_id=%s AND lease_token_hash=%s
                  AND released_at IS NULL""",
            (extend_seconds, task_id, worker_id, lease_token_hash))
        return n == 1

    def finish_lease(self, task_id, *, worker_id, lease_token_hash,
                     generation) -> bool:
        n = self._exec(
            """UPDATE task_leases SET released_at=now()
                WHERE task_id=%s AND worker_id=%s AND lease_token_hash=%s
                  AND generation=%s AND released_at IS NULL""",
            (task_id, worker_id, lease_token_hash, generation))
        return n == 1

    def expire_stale_leases(self, *, now) -> list:
        with self._c.cursor() as cur:
            cur.execute(
                """UPDATE task_leases SET released_at=now(), expired=true
                    WHERE expires_at < to_timestamp(%s) AND released_at IS NULL
                    RETURNING task_id""", (now,))
            rows = cur.fetchall()
        self._c.commit()
        return [r[0] for r in rows]


class PgArtifactRepository(_PgBase):
    def insert_artifact(self, *, task_id, storage_system, uri, sha256, byte_size) -> str:
        row = self._one(
            """INSERT INTO artifacts (task_id, storage_system, uri, sha256, byte_size)
               VALUES (%s,%s,%s,%s,%s) RETURNING id""",
            (task_id, storage_system, uri, sha256, byte_size))
        return row[0]


class PgAuditRepository(_PgBase):
    def append(self, *, actor_ref, action, resource_ref, result, trace_id) -> str:
        row = self._one(
            """INSERT INTO audit_events (actor_ref, action, resource_ref, result, trace_id)
               VALUES (%s,%s,%s,%s,%s) RETURNING id""",
            (actor_ref, action, resource_ref, result, trace_id))
        return str(row[0])

    def retain(self, *, days: int) -> int:
        return self._exec(
            "DELETE FROM audit_events WHERE created_at < now() - make_interval(days=>%s)",
            (days,))


class PgOutboxRepository(_PgBase):
    def enqueue(self, *, aggregate, aggregate_id, kind, payload: dict) -> None:
        self._exec(
            """INSERT INTO outbox (aggregate, aggregate_id, kind, payload)
               VALUES (%s,%s,%s,%s)""",
            (aggregate, aggregate_id, kind, json.dumps(payload)))

    def claim_batch(self, *, limit: int = 50) -> list:
        with self._c.cursor() as cur:
            cur.execute(
                """UPDATE outbox SET dispatched_at=now()
                    WHERE id IN (SELECT id FROM outbox
                                  WHERE dispatched_at IS NULL
                                  ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED)
                    RETURNING id, aggregate, aggregate_id, kind, payload""", (limit,))
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        self._c.commit()
        return rows

    def mark_dispatched(self, event_id: int) -> None:
        self._exec("UPDATE outbox SET dispatched_at=now() WHERE id=%s AND dispatched_at IS NULL",
                   (event_id,))


class PgRepositories:
    """聚合 PG 七域仓储；单连接（单用户轻量控制平面足够，池化属部署优化）。"""

    def __init__(self, conn) -> None:
        self.registry = PgRegistryRepository(conn)
        self.tasks = PgTaskRepository(conn)
        self.approvals = PgApprovalRepository(conn)
        self.leases = PgLeaseRepository(conn)
        self.artifacts = PgArtifactRepository(conn)
        self.audit = PgAuditRepository(conn)
        self.outbox = PgOutboxRepository(conn)


# ══════════════════════ 迁移与恢复（静态可测）══════════════════════

class MigrationRunner:
    """版本化迁移（schema_migrations 表；不自动执行任何迁移——部署 Gate 手动跑）。"""

    def __init__(self, conn, migrations_dir: str) -> None:
        self._c = conn
        self._dir = migrations_dir

    def ensure_version_table(self) -> None:
        with self._c.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        self._c.commit()

    def applied(self) -> list:
        with self._c.cursor() as cur:
            cur.execute("SELECT version FROM schema_migrations ORDER BY applied_at")
            return [r[0] for r in cur.fetchall()]

    def apply(self, version: str, filename: str) -> None:
        import pathlib
        sql = (pathlib.Path(self._dir) / filename).read_text()
        with self._c.cursor() as cur:
            cur.execute(sql)
            cur.execute("INSERT INTO schema_migrations(version) VALUES (%s)", (version,))
        self._c.commit()


def recovery_on_restart(repos: PgRepositories, *, now: float) -> dict:
    """重启恢复：过期租约回收 → 对账态；审计保留窗口执行。返回处置摘要。"""
    expired = repos.leases.expire_stale_leases(now=now)
    reconciled = 0
    for task_id in expired:
        row_task = None
        with repos.tasks._c.cursor() as cur:
            cur.execute("SELECT state FROM tasks WHERE id=%s", (task_id,))
            row_task = cur.fetchone()
        if row_task and row_task[0] in ("LEASED", "RUNNING"):
            if repos.tasks.cas_update_state(task_id, row_task[0],
                                            "NEEDS_RECONCILIATION"):
                reconciled += 1
    repos.audit.append(actor_ref="system", action="restart.recovery",
                       resource_ref="control-plane",
                       result=f"expired_leases={len(expired)} reconciled={reconciled}",
                       trace_id="")
    return {"expired_leases": len(expired), "reconciled": reconciled}


# ═══════════════════════════ 切换机制 ═══════════════════════════

def read_dsn_from_secrets(path: str = "/run/secrets/mwcp_db_dsn") -> str:
    """DSN 只经 secrets 文件；缺失/空 → fail-closed。"""
    try:
        dsn = open(path).read().strip()
    except OSError:
        raise RuntimeError(f"PG repository selected but DSN secret missing at {path} "
                           f"(fail-closed; set MWCP_REPOSITORY=memory for local)")
    if not dsn:
        raise RuntimeError("empty DSN secret (fail-closed)")
    return dsn


def repository_factory(engine=None, store=None, *, mode: str | None = None,
                        conn=None):
    """MWCP_REPOSITORY=memory|postgres（默认 memory）。

    - memory：返回 InMemoryRepositories（本地 RC 行为不变）
    - postgres：需已注入 conn（部署 Gate 时由启动器建立连接）；否则 fail-closed
    """
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
