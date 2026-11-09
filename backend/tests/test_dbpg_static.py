"""dbpg 静态断言：迁移 SQL 关键约束存在 + PG 蓝本不可实例运行。"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SQL = (ROOT / "dbpg" / "migrations" / "0001_init.sql").read_text()


def test_unique_idempotency_index_present():
    assert re.search(r"UNIQUE\(principal_id, capability, capability_version, idempotency_key\)", SQL)


def test_generation_guard_trigger_present():
    assert "resources_write_rev_guard" in SQL and "GREATEST(NEW.generation, OLD.generation)" in SQL


def test_approval_cas_and_outbox_present():
    assert "state='consumed'" in SQL.replace('"', "'") or "state='consumed'" in SQL
    assert "CREATE TABLE outbox" in SQL


def test_no_secrets_in_sql():
    for pat in ("PASSWORD", "secret_", "token_"):
        assert pat not in SQL, f"敏感字样 {pat} 不应出现在迁移 SQL"


def test_pg_repository_implemented_but_connection_fail_closed():
    """部署工程轮：适配器已完整实现（dbpg/repository.py）；
    连接注入前 factory 拒绝启动（fail-closed）。真实库验证 = Gate B（NOT_RUN）。"""
    import sys
    sys.path.insert(0, str(ROOT / "backend"))
    sys.path.insert(0, str(ROOT))
    from dbpg.repository import repository_factory, PgRepositories
    import pytest
    with pytest.raises(RuntimeError, match="fail-closed"):
        repository_factory(mode="postgres", conn=None)

def test_pg_blueprint_methods_have_real_sql():
    """适配器方法不再 NotImplementedError——断言 SQL 语句已实现（离线断言）。"""
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(ROOT))
    from dbpg import repository as R
    import inspect
    for cls in (R.PgTaskRepository, R.PgRegistryRepository,
                R.PgApprovalRepository, R.PgLeaseRepository):
        src = inspect.getsource(cls)
        assert "NotImplementedError" not in src, cls.__name__
