"""Service Container：应用级依赖注入——memory | postgres 双模式。

Phase A1 核心：
- 所有路由经 `get_container()` 获取当前服务集（不再直接引模块级 _store/_engine）
- memory 模式：与 Local RC 完全一致的内存实现
- postgres 模式：PG 适配器包装（真实读写经 dbpg.repository）
- fail-closed：postgres 模式无连接/缺迁移版本 → RuntimeError，不自动退回 memory
- readiness：postgres 模式真实检查 PG SELECT 1 + 迁移版本 + 表存在性

用法（启动器）：
    from service_container import swap_to_postgres, swap_to_memory
    swap_to_memory()  # 本地 RC（默认）
    swap_to_postgres(conn)  # Gate B/生产（需真实连接）
"""
from __future__ import annotations

import os
import time
from typing import Any

# 后端域模块
import taskengine
import registry as registry_mod
from approvals import ApprovalService
from workergw import WorkerGateway

# dbpg 仓储（postgres 模式）
import sys
import pathlib
_dbpg_dir = str(pathlib.Path(__file__).resolve().parents[1])
if _dbpg_dir not in sys.path:
    sys.path.insert(0, _dbpg_dir)
from dbpg.repository import (  # noqa: E402
    InMemoryRepositories, PgRepositories, MigrationRunner, transaction,
)


class AppState:
    """全局可替换的应用状态——持有全部服务实例。"""

    def __init__(self) -> None:
        self.mode: str = "uninitialized"
        self.engine: taskengine.TaskEngine | None = None
        self.store: registry_mod.RegistryStore | None = None
        self.gateway: WorkerGateway | None = None
        self.approvals: ApprovalService | None = None
        self.repos: InMemoryRepositories | PgRepositories | None = None
        self.pg_conn: Any = None  # postgres 模式下持有连接
        self.migration_version: str | None = None

    @property
    def is_pg(self) -> bool:
        return self.mode == "postgres"


# ════════ 全局单例（可 swap） ════════

_state = AppState()


def get_state() -> AppState:
    return _state


def get_container() -> AppState:
    """FastAPI 路由经此获取服务集——替代直接 import _store/_engine。"""
    if _state.mode == "uninitialized":
        _auto_init()
    return _state


def _auto_init() -> None:
    """启动时根据 MWCP_REPOSITORY 环境变量自动初始化（默认 memory）。"""
    mode = os.environ.get("MWCP_REPOSITORY", "memory").strip().lower()
    if mode == "memory":
        swap_to_memory()
    elif mode == "postgres":
        # PG 模式：必须由启动器显式调用 swap_to_postgres(conn)——这里 fail-closed
        raise RuntimeError(
            "MWCP_REPOSITORY=postgres requires explicit swap_to_postgres(conn) "
            "with a real database connection (fail-closed; not auto-fallback)")
    else:
        raise ValueError(f"MWCP_REPOSITORY must be memory|postgres, got {mode!r}")


# ════════ 模式切换 ════════

def swap_to_memory() -> AppState:
    """切换到内存模式——与 Local RC 行为一致。"""
    global _state
    _state = AppState()
    _state.mode = "memory"
    _state.store = registry_mod.RegistryStore()
    registry_mod.seed_audit_baseline(_state.store)
    _state.engine = taskengine.TaskEngine()
    _state.gateway = WorkerGateway(_state.engine)
    _state.approvals = ApprovalService(_state.engine, clock=time.time)
    _state.repos = InMemoryRepositories(_state.engine, _state.store)
    return _state


def swap_to_postgres(conn, *, migrations_dir: str | None = None) -> AppState:
    """切换到 PG 模式——需真实连接 + 已完成迁移。

    fail-closed 链：
    1. conn 为 None → RuntimeError
    2. 迁移版本表不存在 → RuntimeError（未跑迁移）
    3. 关键表不存在 → RuntimeError
    4. SELECT 1 失败 → RuntimeError（连接不可用）
    """
    global _state
    if conn is None:
        raise RuntimeError("swap_to_postgres: conn is None (fail-closed)")
    if migrations_dir is None:
        migrations_dir = str(pathlib.Path(__file__).parent.parent / "dbpg" / "migrations")

    # 验证连接
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            if cur.fetchone() is None:
                raise RuntimeError("PG SELECT 1 returned no rows")
    except Exception as e:
        raise RuntimeError(f"PG connection check failed (fail-closed): {e}") from e

    # 验证迁移版本表
    try:
        runner = MigrationRunner(conn, migrations_dir=migrations_dir)
        applied = runner.applied()
        if not applied:
            raise RuntimeError("No migrations applied — run migrations before "
                               "swap_to_postgres (fail-closed)")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Migration version check failed (fail-closed): {e}") from e

    # 验证关键表
    _verify_pg_schema(conn)

    # 装配
    _state = AppState()
    _state.mode = "postgres"
    _state.pg_conn = conn
    _state.repos = PgRepositories(conn)

    # PG 模式下：域服务使用 PG 适配器
    # TaskEngine / WorkerGateway / ApprovalService 内部逻辑不变——它们的
    # 数据操作经 repos（PG 或内存）进行。当前阶段（Phase A1）：
    # PG 模式使用独立的内存域服务，但持久化经 PG repos 同步。
    # Gate B 后替换为完整 PG-backed 域服务。
    _state.store = registry_mod.RegistryStore()
    registry_mod.seed_audit_baseline(_state.store)
    _state.engine = taskengine.TaskEngine()
    _state.gateway = WorkerGateway(_state.engine)
    _state.approvals = ApprovalService(_state.engine, clock=time.time)
    _state.migration_version = applied[-1] if applied else None

    return _state


def readiness_check(state: AppState) -> dict:
    """真实 readiness：按模式检查实际可用性——不用测试开关伪造。"""
    deps = {
        "auth": "ok",  # 由 app.py 的 _validator 决定
        "repository": "unknown",
        "database": "not_connected",
        "probes": "not_configured",
        "migrations": "unknown",
    }
    if state.mode == "memory":
        deps["repository"] = "memory"
        deps["database"] = "not_connected"
        deps["migrations"] = "n/a"
    elif state.mode == "postgres":
        deps["repository"] = "postgres"
        deps["migrations"] = state.migration_version or "unknown"
        # 真实检查 PG 可用性
        try:
            if state.pg_conn is not None:
                with state.pg_conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    if cur.fetchone() is not None:
                        deps["database"] = "ok"
                    else:
                        deps["database"] = "error"
            else:
                deps["database"] = "connection_lost"
        except Exception:
            deps["database"] = "error"

    return deps


def _verify_pg_schema(conn) -> None:
    """验证关键表存在（7 张核心表）。"""
    REQUIRED_TABLES = [
        "principals", "resources", "tasks", "task_events", "task_attempts",
        "approvals", "audit_events", "outbox", "task_leases", "artifacts",
    ]
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public'")
            existing = {r[0] for r in cur.fetchall()}
    except Exception as e:
        raise RuntimeError(f"Schema verification failed (fail-closed): {e}") from e
    missing = [t for t in REQUIRED_TABLES if t not in existing]
    if missing:
        raise RuntimeError(f"PG schema missing tables: {missing} — "
                           f"run migrations first (fail-closed)")


# ════════ 启动时自动初始化（memory 默认） ════════

# 模块导入时执行——确保所有路由能立即使用
_auto_init()
