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


def test_pg_repository_is_explicitly_not_run():
    import sys
    sys.path.insert(0, str(ROOT / "backend"))
    from dbpg_shim import PgRepoProbe  # noqa: F401

def test_pg_blueprint_methods_raise_not_implemented():
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from dbpg_shim import _mod
    repo = _mod.PgTaskRepo(conn=None)
    for fn, args in [("insert_task", {}), ("cas_update_state", ("t", "a", "b")),
                     ("conditional_finish", ("t", 1, "h", "SUCCEEDED"))]:
        with pytest.raises(NotImplementedError):
            getattr(repo, fn)(*args)
