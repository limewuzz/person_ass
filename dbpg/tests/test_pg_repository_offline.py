"""PG 仓储离线单元测试：SQL 文本/参数/CAS 语义/事务边界/切换机制/恢复流程。

全部使用 FakeConn/FakeCursor（内存行为模拟 DB-API），不连接任何真实数据库。
真实 PG 行为验证 = Gate B（隔离实验，另行授权）。运行：
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest dbpg/tests -q
"""
import os
import sys
import pathlib
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "backend"))

import dbpg.repository as R  # noqa: E402


# ───────────────────────── 假连接（记录 SQL+参数，可编程行结果） ─────────────────────────

class FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self.rowcount = 0
        self._rows: list = []
        self._cols: list = []

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def execute(self, sql, params=()):
        self._conn.calls.append((sql, tuple(params)))
        matcher = self._conn.responder
        sql_norm = " ".join(sql.split()).lower()
        self._rows, self.rowcount = matcher(sql_norm, tuple(params))

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    @property
    def description(self):
        return [(c,) for c in self._cols]


class FakeConn:
    def __init__(self, responder):
        self.calls: list = []
        self.responder = responder
        self.commits = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1


def conn_returning(rows=None, rowcount=0):
    def matcher(sql, params):
        return (rows or []), rowcount
    return FakeConn(matcher)


def last_sql(conn):
    return " ".join(conn.calls[-1][0].split()).lower()  # 规范化：压空白+小写

def last_params(conn):
    return conn.calls[-1][1]


# ───────────────────────── Registry：generation CAS / ABA ─────────────────────────

def test_bump_generation_uses_expected_generation_in_where():
    c = conn_returning(rows=[(7,)])
    repo = R.PgRegistryRepository(c)
    assert repo.bump_generation("svc.x", expected_generation=3) == 7
    sql = last_sql(c)
    assert "where id=%s and generation=%s" in sql
    assert last_params(c) == ("svc.x", 3)
    assert c.commits == 1


def test_bump_generation_conflict_raises():
    c = conn_returning(rows=None)
    repo = R.PgRegistryRepository(c)
    with pytest.raises(ValueError, match="generation conflict"):
        repo.bump_generation("svc.x", expected_generation=3)


def test_write_observation_dual_snapshot_aba_guard():
    c = conn_returning(rowcount=1)
    repo = R.PgRegistryRepository(c)
    ok = repo.write_observation("svc.x", health="healthy", observed_at="t1",
                                received_at="t2", ttl_seconds=60,
                                source="probe:http.get",
                                expected_generation=4, expected_write_rev=2)
    assert ok is True
    sql = last_sql(c)
    assert "generation=%s" in sql and "write_rev=%s" in sql  # 双快照比对
    assert "lifecycle_state='active'" in sql


def test_write_observation_zero_rows_returns_false():
    c = conn_returning(rowcount=0)
    repo = R.PgRegistryRepository(c)
    assert repo.write_observation("x", health="h", observed_at="t", received_at="t",
                                  ttl_seconds=1, source="s",
                                  expected_generation=1, expected_write_rev=0) is False


# ───────────────────────── Task：幂等 / CAS / 迟到拒绝 ─────────────────────────

BASE_TASK = dict(principal_id="u", capability="cap", capability_version=1,
                 resource_id="r", idempotency_key="k" * 12, request_hash="h" * 64,
                 origin_channel="web", origin_external_ref=None, work_item_id=None,
                 requires_approval=False, risk="READ", dry_run=False,
                 args_redacted={"a": 1}, trace_id="t-1")


def test_insert_task_on_conflict_do_nothing_then_replay_lookup():
    calls = {"insert_done": False}
    def matcher(sql, p):
        if "insert into tasks" in sql:
            calls["insert_done"] = True
            return ([("tk-new",)], 1) if not calls.get("second") else ([], 0)
        if "select id, request_hash" in sql:
            return ([("tk-new", "h" * 64)], 1)   # 同 payload → 重放
        return ([], 0)
    c = FakeConn(matcher)
    repo = R.PgTaskRepository(c)
    tid, replayed = repo.insert_task(**BASE_TASK)
    assert replayed is False and tid == "tk-new"
    assert "on conflict (principal_id, capability, capability_version, idempotency_key) do nothing" \
        in last_sql(c)
    # 第二次：INSERT 冲突 0 行 → find → 同 hash 重放
    calls["second"] = True
    tid2, replayed2 = repo.insert_task(**BASE_TASK)
    assert replayed2 is True and tid2 == "tk-new"


def test_insert_task_same_key_different_payload_conflict():
    def matcher(sql, p):
        if "insert into tasks" in sql:
            return ([], 0)          # 冲突：0 行
        if "select id, request_hash" in sql:
            return ([("tk-old", "different-hash")], 1)
        return ([], 0)
    repo = R.PgTaskRepository(FakeConn(matcher))
    with pytest.raises(RuntimeError, match="idempotency conflict"):
        repo.insert_task(**BASE_TASK)


def test_cas_update_state_row_level_lock():
    c = conn_returning(rowcount=1)
    repo = R.PgTaskRepository(c)
    assert repo.cas_update_state("t1", "QUEUED", "LEASED") is True
    sql = last_sql(c)
    assert "where id=%s and state=%s" in sql and "updated_at=now()" in sql


def test_conditional_finish_requires_active_lease():
    c = conn_returning(rowcount=1)
    repo = R.PgTaskRepository(c)
    ok = repo.conditional_finish("t1", generation=2, lease_token_hash="h",
                                 outcome="SUCCEEDED", result_summary="ok")
    assert ok is True
    sql = last_sql(c)
    assert "exists (select 1 from task_leases" in sql
    assert "released_at is null" in sql        # 已释放（迟到）→ 0 行拒绝


def test_load_open_tasks_excludes_terminal():
    c = FakeConn(lambda sql, p: ([("SUCCEEDED",), ("QUEUED",)], 2)
                 if "state not in" in sql else ([], 0))
    repo = R.PgTaskRepository(c)
    rows = repo.load_open_tasks()
    assert rows and "not in ('succeeded','failed','canceled','expired')" in last_sql(c)


# ───────────────────────── Approval：一次性消费 ─────────────────────────

def test_consume_once_single_statement_atomic():
    c = conn_returning(rowcount=1)
    repo = R.PgApprovalRepository(c)
    assert repo.consume_once("ap-1", confirm_token="tok", payload_hash="h") is True
    sql = last_sql(c)
    assert "state='approved'" in sql and "confirm_token=%s" in sql \
        and "payload_hash=%s" in sql
    assert "select" not in sql.split("update")[0]  # 单语句，无 check-then-write


def test_consume_once_zero_rows_false():
    c = conn_returning(rowcount=0)
    assert R.PgApprovalRepository(c).consume_once(
        "ap-1", confirm_token="t", payload_hash="h") is False


def test_cas_decide_checks_expiry_in_where():
    c = conn_returning(rowcount=1)
    repo = R.PgApprovalRepository(c)
    assert repo.cas_decide("ap-1", decision="approved", actor="u") is True
    assert "expires_at > now()" in last_sql(c)


# ───────────────────────── Lease：过期回收/迟到释放 ─────────────────────────

def test_expire_stale_leases_returns_task_ids():
    c = conn_returning(rows=[("t1",), ("t2",)], rowcount=2)
    repo = R.PgLeaseRepository(c)
    assert repo.expire_stale_leases(now=1000.0) == ["t1", "t2"]
    assert "expires_at < to_timestamp(%s)" in last_sql(c)


def test_finish_lease_generation_bound():
    c = conn_returning(rowcount=1)
    repo = R.PgLeaseRepository(c)
    assert repo.finish_lease("t1", worker_id="w", lease_token_hash="h",
                             generation=3) is True
    sql = last_sql(c)
    assert "generation=%s" in sql and "released_at is null" in sql


# ───────────────────────── Outbox：FOR UPDATE SKIP LOCKED ─────────────────────────

def test_outbox_claim_uses_skip_locked():
    c = FakeConn(lambda sql, p: ([], 0))
    repo = R.PgOutboxRepository(c)
    repo.claim_batch(limit=10)
    sql = last_sql(c)
    assert "for update skip locked" in sql and "dispatched_at is null" in sql


# ───────────────────────── 迁移/恢复/切换 ─────────────────────────

def test_migration_runner_versions():
    c = FakeConn(lambda sql, p: ([("0001_init.sql",)], 1)
                 if "select version from" in sql else ([], 0))
    runner = R.MigrationRunner(c, migrations_dir="/nonexistent")
    runner.ensure_version_table()
    assert "create table if not exists schema_migrations" in last_sql(c)


def test_recovery_flow_reconciles_expired_lease_tasks():
    def matcher(sql, p):
        if "update task_leases set released_at=now(), expired=true" in sql:
            return ([("t1",), ("t2",)], 2)
        if "select state from tasks where id=%s" in sql:
            return ([("LEASED",)], 1)
        if "update tasks set state" in sql:
            return ([], 1)
        if "insert into audit_events" in sql:
            return ([("ae-1",)], 1)
        return ([], 0)
    c = FakeConn(matcher)
    repos = R.PgRepositories(c)
    summary = R.recovery_on_restart(repos, now=2000.0)
    assert summary == {"expired_leases": 2, "reconciled": 2}


def test_factory_memory_default_and_fail_closed():
    eng, st = object(), object()
    repos = R.repository_factory(engine=eng, store=st, mode="memory")
    assert isinstance(repos, R.InMemoryRepositories)
    with pytest.raises(RuntimeError, match="fail-closed"):
        R.repository_factory(mode="postgres", conn=None)  # 无连接拒绝启动
    with pytest.raises(ValueError):
        R.repository_factory(mode="bogus")


def test_factory_env_switch(monkeypatch):
    monkeypatch.setenv("MWCP_REPOSITORY", "memory")
    repos = R.repository_factory(engine=1, store=2)
    assert isinstance(repos, R.InMemoryRepositories)
    monkeypatch.setenv("MWCP_REPOSITORY", "postgres")
    with pytest.raises(RuntimeError):
        R.repository_factory(engine=1, store=2)  # 无 conn → fail-closed


def test_dsn_secret_missing_fail_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("MWCP_DSN_PATH", raising=False)
    with pytest.raises(RuntimeError, match="fail-closed"):
        R.read_dsn_from_secrets(path=str(tmp_path / "nope"))


def test_dsn_secret_present(tmp_path):
    f = tmp_path / "dsn"
    f.write_text("postgresql://mwcp_app:x@mwcp-db:5432/control_plane\n")
    assert R.read_dsn_from_secrets(path=str(f)).startswith("postgresql://")


# ───────────────────────── 迁移 SQL 静态断言（0001+0002 与适配器一致） ─────────────────────────

MIG = pathlib.Path(__file__).resolve().parents[1] / "migrations"


def test_0002_has_leases_and_artifacts_tables():
    sql = (MIG / "0002_leases_artifacts.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS task_leases" in sql
    assert "CREATE TABLE IF NOT EXISTS artifacts" in sql


def test_0001_has_idempotency_unique_and_outbox():
    sql = (MIG / "0001_init.sql").read_text()
    assert "UNIQUE(principal_id, capability, capability_version, idempotency_key)" in sql
    assert "CREATE TABLE outbox" in sql
