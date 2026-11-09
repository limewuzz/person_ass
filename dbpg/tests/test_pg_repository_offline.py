"""PG 仓储离线测试（Gate B 前置整改版）：事务边界/状态约束/Outbox 可靠投递/装配切换。

FakeConn 支持编程行为（rows/rowcount 状态机），不连任何真实数据库。
新增断言风格：参数数量、SQL↔DDL 列一致性、事务组合语义、负向状态机。
"""
import os
import sys
import pathlib
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

import dbpg.repository as R  # noqa: E402


class FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self.rowcount = 0
        self._rows: list = []

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def execute(self, sql, params=()):
        norm_sql = " ".join(sql.split()).lower()
        self._conn.calls.append((norm_sql, tuple(params)))
        if self._conn.error_on and self._conn.error_on in norm_sql:
            raise RuntimeError(f"SQL error simulated: {self._conn.error_on!r} in {norm_sql[:60]}")
        rows, rc = self._conn.responder(norm_sql, tuple(params))
        self._rows = rows
        self.rowcount = rc

    def fetchone(self): return self._rows[0] if self._rows else None
    def fetchall(self): return list(self._rows)
    @property
    def description(self):
        cols = self._conn.columns or [f"c{i}" for i in range(
            len(self._rows[0]) if self._rows else 0)]
        return [(c,) for c in cols]


class FakeConn:
    def __init__(self, responder, columns=None, error_on=None):
        self.calls = []
        self.responder = responder
        self.commits = 0
        self.rollbacks = 0
        self.columns = columns
        self.error_on = error_on  # SQL 子串命中即 raise（模拟语法错误/约束冲突）
    def cursor(self): return FakeCursor(self)
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1


def norm(sql): return " ".join(sql.split()).lower()
def last_sql(c): return c.calls[-1][0]
def last_params(c): return c.calls[-1][1]


# ════════ 事务边界 ════════

def test_pg_base_does_not_auto_commit():
    c = FakeConn(lambda s, p: ([], 0))
    repo = R.PgRegistryRepository(c)
    repo.upsert_resource("x", kind="service", owner_system="o",
                         display_name="d", node_id="n")
    assert c.commits == 0 and c.rollbacks == 0  # 不自动 commit


def test_transaction_context_commit_on_success():
    c = FakeConn(lambda s, p: ([("ae-1",)], 1) if "insert into audit_events" in s else ([], 0))
    with R.transaction(c):
        R.PgAuditRepository(c).append(actor_ref="a", action="b",
                                      resource_ref="c", result="d", trace_id="")
    assert c.commits == 1 and c.rollbacks == 0


def test_transaction_context_rollback_on_exception():
    c = FakeConn(lambda s, p: ([("ae-1",)], 1) if "insert into audit_events" in s else ([], 0))
    with pytest.raises(ValueError, match="boom"):
        with R.transaction(c):
            R.PgAuditRepository(c).append(actor_ref="a", action="b",
                                          resource_ref="c", result="d", trace_id="")
            raise ValueError("boom")
    assert c.commits == 0 and c.rollbacks == 1


def test_migration_runner_atomic_rollback():
    c = FakeConn(lambda s, p: ([], 0), error_on="this is not sql")
    tmp = pathlib.Path("/tmp/mig_test_dir"); tmp.mkdir(exist_ok=True)
    (tmp / "bad.sql").write_text("CREATE TABLE t1(id int);\nTHIS IS NOT SQL;")
    runner = R.MigrationRunner(c, migrations_dir=str(tmp))
    with pytest.raises(Exception):
        runner.apply("0001_bad", "bad.sql")
    assert c.rollbacks >= 1 and c.commits == 0


def test_migration_split_statements_handles_dollar_blocks():
    sql = ("CREATE TABLE a(id int);\n-- comment\n"
           "CREATE FUNCTION f() RETURNS void AS $$ BEGIN\n NULL; END $$ LANGUAGE plpgsql;\n")
    stmts = R.MigrationRunner._split_statements(sql)
    assert len(stmts) == 2  # 函数体整体不切分
    assert "plpgsql" in stmts[1]


# ════════ 状态约束 ════════

def test_consume_once_includes_expiry_check():
    c = FakeConn(lambda s, p: ([], 1))
    assert R.PgApprovalRepository(c).consume_once(
        "ap", confirm_token="t", payload_hash="h") is True
    sql = last_sql(c)
    assert "expires_at is null or expires_at > now()" in sql


def test_heartbeat_lease_rejects_expired():
    c = FakeConn(lambda s, p: ([], 1))
    assert R.PgLeaseRepository(c).heartbeat_lease(
        "t", worker_id="w", lease_token_hash="h", extend_seconds=30) is True
    sql = last_sql(c)
    assert "expires_at > now()" in sql and "released_at is null" in sql


def test_finish_lease_checks_generation_and_expiry():
    c = FakeConn(lambda s, p: ([], 1))
    assert R.PgLeaseRepository(c).finish_lease(
        "t", worker_id="w", lease_token_hash="h", generation=3) is True
    sql = last_sql(c)
    assert "generation=%s" in sql and "expires_at > now()" in sql


def test_conditional_finish_requires_active_unexpired_lease():
    c = FakeConn(lambda s, p: ([], 1))
    assert R.PgTaskRepository(c).conditional_finish(
        "t", generation=2, lease_token_hash="h",
        outcome="SUCCEEDED", result_summary="ok") is True
    sql = last_sql(c)
    assert "l.generation=%s" in sql
    assert "l.expires_at > now()" in sql
    assert "l.released_at is null" in sql


def test_bump_generation_owner_change_invalidates_old_auth():
    """资源权威变更 → generation 递增 → 旧 generation 的观测写入被拒（ABA/旧授权失效）。"""
    state = {"gen": 3}
    def matcher(s, p):
        if "update resources set generation" in s:
            state["gen"] += 1
            return ([(state["gen"],)], 1)
        if "update resources set health" in s:
            return ([], 0)  # 旧 generation → 0 行
        return ([], 0)
    c = FakeConn(matcher)
    repos = R.PgRegistryRepository(c)
    new_gen = repos.bump_generation("svc.x", expected_generation=3)
    assert new_gen == 4
    ok = repos.write_observation("svc.x", health="healthy", observed_at="t",
                                 received_at="t", ttl_seconds=60, source="probe",
                                 expected_generation=3, expected_write_rev=0)
    assert ok is False


# ════════ Outbox 可靠投递 ════════

def test_outbox_claim_is_not_delivery():
    c = FakeConn(lambda s, p: ([{"id": 1, "kind": "task.created",
                                 "payload": "{}", "attempt_count": 1}], 1))
    events = R.PgOutboxRepository(c).claim_batch(limit=5, lease_seconds=30)
    assert len(events) == 1
    sql = last_sql(c)
    assert "claimed_at=now()" in sql
    assert "claim_expires_at=now() + make_interval" in sql
    assert "attempt_count = attempt_count + 1" in sql
    assert "dispatched_at=now()" not in sql.split("where")[0]


def test_outbox_confirm_after_claim():
    c = FakeConn(lambda s, p: ([], 1))
    assert R.PgOutboxRepository(c).confirm_dispatched(
        42, claim_token="tok") is True
    sql = last_sql(c)
    assert "dispatched_at=now()" in sql
    assert "claim_token=%s" in sql


def test_outbox_fail_releases_claim_for_retry():
    c = FakeConn(lambda s, p: ([], 1))
    assert R.PgOutboxRepository(c).fail_delivery(
        42, claim_token="tok", error="timeout") is True
    sql = last_sql(c)
    assert "claimed_at=null" in sql and "last_error=%s" in sql


def test_outbox_crash_reclaim_expired():
    c = FakeConn(lambda s, p: ([(7,), (8,)], 2), columns=["id"])
    ids = R.PgOutboxRepository(c).reclaim_expired(now=2000.0)
    assert ids == [7, 8]
    sql = last_sql(c)
    assert "claim_expires_at < to_timestamp" in sql
    assert "claimed_at=null" in sql
    assert "dispatched_at is null" in sql


def test_outbox_full_lifecycle_claim_confirm_no_reclaim():
    """领取→确认→过期回收不捡已投递事件。"""
    delivered = {"done": False}
    def matcher(s, p):
        if "update outbox set" in s and "claim_token=%s" in s:
            return ([(1, "agg", "1", "ev", "{}", 1, "tok_1")], 1)
        if "update outbox set dispatched_at=now()" in s and not delivered["done"]:
            delivered["done"] = True
            return ([], 1)
        if "update outbox set claim_token=null, claimed_at=null" in s:
            return ([], 0)
        return ([], 0)
    c = FakeConn(matcher,
                 columns=["id", "aggregate", "aggregate_id", "kind", "payload",
                          "attempt_count", "claim_token"])
    repo = R.PgOutboxRepository(c)
    events = repo.claim_batch(limit=1)
    assert repo.confirm_dispatched(events[0]["id"],
                                   claim_token=events[0]["claim_token"]) is True
    assert repo.reclaim_expired(now=99999.0) == []


# ════════ SQL ↔ DDL 列一致性 ════════

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "migrations"
ALL_MIG_SQL = "\n".join((MIG_DIR / f).read_text()
                        for f in sorted(MIG_DIR.glob("*.sql")))


@pytest.mark.parametrize("table,cols", [
    ("tasks", ["dry_run", "args_redacted", "origin_external_ref", "work_item_id",
               "trace_id", "idempotency_key", "request_hash", "requires_approval", "risk"]),
    ("task_leases", ["lease_token_hash", "generation", "expires_at", "released_at", "expired"]),
    ("approvals", ["payload_hash", "confirm_token", "expires_at", "consumed_at", "decided_by"]),
    ("outbox", ["claimed_at", "claim_expires_at", "attempt_count", "last_error",
                "dispatched_at", "payload"]),
    ("resources", ["generation", "write_rev", "lifecycle_state", "health",
                   "observed_at", "received_at", "ttl_seconds", "source"]),
    ("audit_events", ["actor_ref", "action", "resource_ref", "result", "trace_id"]),
    ("artifacts", ["task_id", "storage_system", "uri", "sha256", "byte_size"]),
])
def test_ddl_has_all_columns_referenced_by_sql(table, cols):
    for col in cols:
        assert col in ALL_MIG_SQL, f"{table}.{col} missing from migrations"


def test_param_count_matches_placeholders():
    """参数数量 vs %s 占位符——逐方法校验。"""
    # consume_once
    c = FakeConn(lambda s, p: ([], 1))
    R.PgApprovalRepository(c).consume_once("ap", confirm_token="t", payload_hash="h")
    assert len(last_params(c)) == 3 and last_sql(c).count("%s") == 3
    # heartbeat_lease
    c2 = FakeConn(lambda s, p: ([], 1))
    R.PgLeaseRepository(c2).heartbeat_lease("t", worker_id="w",
                                            lease_token_hash="h", extend_seconds=30)
    assert len(last_params(c2)) == 4 and last_sql(c2).count("%s") == 4
    # finish_lease
    c3 = FakeConn(lambda s, p: ([], 1))
    R.PgLeaseRepository(c3).finish_lease("t", worker_id="w",
                                         lease_token_hash="h", generation=3)
    assert len(last_params(c3)) == 4 and last_sql(c3).count("%s") == 4
    # bump_generation
    c4 = FakeConn(lambda s, p: ([(4,)], 1))
    R.PgRegistryRepository(c4).bump_generation("x", expected_generation=3)
    assert len(last_params(c4)) == 2 and last_sql(c4).count("%s") == 2


# ════════ 装配与切换（fail-closed） ════════

def test_factory_memory_default():
    repos = R.repository_factory(engine=1, store=2)
    assert isinstance(repos, R.InMemoryRepositories)


def test_factory_postgres_fail_closed_without_conn():
    with pytest.raises(RuntimeError, match="fail-closed"):
        R.repository_factory(mode="postgres", conn=None)


def test_factory_env_postgres_fail_closed(monkeypatch):
    monkeypatch.setenv("MWCP_REPOSITORY", "postgres")
    with pytest.raises(RuntimeError):
        R.repository_factory(engine=1, store=2)


def test_assemble_app_memory_mode():
    app, repos = R.assemble_app(mode="memory")
    assert repos is not None
    assert hasattr(repos, "engine") and hasattr(repos, "store")


def test_assemble_app_postgres_fail_closed():
    with pytest.raises(RuntimeError, match="fail-closed"):
        R.assemble_app(mode="postgres", conn=None)


def test_dsn_missing_fail_closed(tmp_path):
    with pytest.raises(RuntimeError, match="fail-closed"):
        R.read_dsn_from_secrets(path=str(tmp_path / "nope"))


def test_dsn_present(tmp_path):
    f = tmp_path / "dsn"; f.write_text("postgresql://u:p@h:5432/db\n")
    assert R.read_dsn_from_secrets(path=str(f)).startswith("postgresql://")


# ════════ 0003 迁移 ════════

def test_0003_adds_missing_columns_and_outbox_reliability():
    sql = (MIG_DIR / "0003_pre_gate_b.sql").read_text()
    for snippet in ("ADD COLUMN IF NOT EXISTS dry_run",
                    "ADD COLUMN IF NOT EXISTS args_redacted",
                    "ADD COLUMN IF NOT EXISTS claimed_at",
                    "ADD COLUMN IF NOT EXISTS claim_expires_at",
                    "ADD COLUMN IF NOT EXISTS attempt_count",
                    "idx_outbox_reclaim"):
        assert snippet in sql, snippet


# ════════ Phase A2: MigrationRunner — advisory lock + checksum + 原子 ════════

def test_migration_uses_advisory_lock():
    c = FakeConn(lambda s, p: ([], 0))
    runner = R.MigrationRunner(c, migrations_dir="/tmp")
    tmp = pathlib.Path("/tmp/mig_lock_test"); tmp.mkdir(exist_ok=True)
    (tmp / "0001_test.sql").write_text("CREATE TABLE t(id int);")
    runner2 = R.MigrationRunner(c, migrations_dir=str(tmp))
    try:
        runner2.apply("0001_test", "0001_test.sql")
    except Exception:
        pass
    lock_sql = [sql for sql, _ in c.calls if "pg_advisory_xact_lock" in sql]
    assert lock_sql, "advisory lock not used"


def test_migration_rejects_duplicate():
    def matcher(s, p):
        if "select 1 from schema_migrations where version" in s:
            return ([(1,)], 1)  # 已存在
        return ([], 0)
    c = FakeConn(matcher)
    tmp = pathlib.Path("/tmp/mig_dup"); tmp.mkdir(exist_ok=True)
    (tmp / "x.sql").write_text("SELECT 1;")
    runner = R.MigrationRunner(c, migrations_dir=str(tmp))
    import pytest as _pytest
    with _pytest.raises(ValueError, match="already applied"):
        runner.apply("0001_x", "x.sql")


def test_migration_file_checksum_recorded():
    """版本记录包含 checksum——防已应用迁移被改写。"""
    c = FakeConn(lambda s, p: ([], 0))
    tmp = pathlib.Path("/tmp/mig_hash"); tmp.mkdir(exist_ok=True)
    (tmp / "0001_h.sql").write_text("CREATE TABLE h(id int);")
    runner = R.MigrationRunner(c, migrations_dir=str(tmp))
    try:
        runner.apply("0001_h", "0001_h.sql")
    except Exception:
        pass
    insert = [p for sql, p in c.calls if "insert into schema_migrations" in sql]
    assert insert and len(insert[0]) == 2  # (version, checksum)
    assert len(insert[0][1]) == 64  # SHA-256 hex


def test_migration_no_begin_commit_in_files():
    """迁移文件不含 BEGIN;/COMMIT;——事务由 Runner 统一管理。"""
    for f in sorted(MIG_DIR.glob("*.sql")):
        content = f.read_text()
        assert "BEGIN;" not in content, f"{f.name} contains BEGIN;"
        assert "COMMIT;" not in content, f"{f.name} contains COMMIT;"


# ════════ Phase A3: Registry ABA — 权威变更原子 bump ════════

def test_bump_generation_with_owner_change_atomic():
    """owner 变更 + generation 推进在同一 UPDATE——不依赖调用方额外调 bump。"""
    c = FakeConn(lambda s, p: ([(5,)], 1))
    repo = R.PgRegistryRepository(c)
    result = repo.bump_generation("svc.x", expected_generation=3, new_owner="owner-beta")
    assert result == 5
    sql = last_sql(c)
    assert "owner_system = %s" in sql  # owner 变更在同一语句
    assert "generation = nextval" in sql  # generation 推进也在
    params = last_params(c)
    assert "owner-beta" in params


def test_bump_generation_kind_and_node_atomic():
    c = FakeConn(lambda s, p: ([(6,)], 1))
    repo = R.PgRegistryRepository(c)
    repo.bump_generation("svc.x", expected_generation=5,
                         new_kind="agent", new_node="us-server")
    sql = last_sql(c)
    assert "kind = %s" in sql and "node_id = %s" in sql


def test_bump_generation_aba_detected():
    """A→B→A：generation 已推进两次 → expected 旧值无法通过。"""
    c = FakeConn(lambda s, p: ([], 0))  # 0 行=generation 不匹配
    repo = R.PgRegistryRepository(c)
    import pytest as _pytest
    with _pytest.raises(ValueError, match="generation conflict"):
        repo.bump_generation("svc.x", expected_generation=1)  # 旧值=ABA 后无法通过


# ════════ Phase A4: Outbox — claim token + ACK + 退避 ════════

def test_outbox_claim_assigns_unique_token():
    c = FakeConn(lambda s, p: ([(1, "agg", "1", "ev", "{}", 1, "tok_abc")], 1),
                 columns=["id", "aggregate", "aggregate_id", "kind", "payload",
                          "attempt_count", "claim_token"])
    events = R.PgOutboxRepository(c).claim_batch(limit=1)
    assert events and events[0]["claim_token"] == "tok_abc"
    sql = last_sql(c)
    assert "claim_token=%s" in sql  # 分配 token


def test_outbox_ack_requires_correct_token():
    c = FakeConn(lambda s, p: ([], 1))
    assert R.PgOutboxRepository(c).confirm_dispatched(
        42, claim_token="correct_token") is True
    sql = last_sql(c)
    assert "claim_token=%s" in sql  # 验证 token
    assert "claim_expires_at > now()" in sql  # 验证未过期


def test_outbox_ack_wrong_token_rejected():
    c = FakeConn(lambda s, p: ([], 0))  # 0 行=token 不匹配
    assert R.PgOutboxRepository(c).confirm_dispatched(
        42, claim_token="wrong") is False


def test_outbox_fail_sets_next_retry_at():
    c = FakeConn(lambda s, p: ([], 1))
    assert R.PgOutboxRepository(c).fail_delivery(
        42, claim_token="tok", error="timeout") is True
    sql = last_sql(c)
    assert "next_retry_at=now() + make_interval" in sql  # 退避


def test_outbox_max_attempts_dead_letter():
    """有界重试：attempt_count >= MAX_ATTEMPTS 的事件不再被领取。"""
    c = FakeConn(lambda s, p: ([], 0))
    repo = R.PgOutboxRepository(c)
    repo.claim_batch(limit=1)
    sql = last_sql(c)
    assert "attempt_count < %s" in sql  # 领取时排除已达上限的


def test_outbox_at_least_once_not_exactly_once():
    """at-least-once：reclaim 后可重新领取（同一事件可能投递多次——消费者必须幂等）。"""
    c = FakeConn(lambda s, p: ([(7,)], 1), columns=["id"])
    ids = R.PgOutboxRepository(c).reclaim_expired(now=2000.0)
    assert 7 in ids  # 可重投
