"""P1-05 Registry 契约测试：形状 / provenance / UNKNOWN / STALE 衰减 / 分页 / 过滤。"""
import time

import pytest
from fastapi.testclient import TestClient

import app as app_mod
from auth import mint_token

SECRET = "test-secret-only-for-local-tests"


@pytest.fixture()
def client():
    return TestClient(app_mod.app, raise_server_exceptions=False)


@pytest.fixture()
def hdr():
    t = mint_token(SECRET, sub="u1", typ="actor", role="admin",
                   scopes=["health:read", "registry:read", "probes:read", "approvals:read",
                           "admin:read"], jti="jti-registry")
    return {"Authorization": f"Bearer {t}"}


# ---- 契约形状（required 字段齐备）----

def test_node_shape_matches_contract(client, hdr):
    r = client.get("/api/v1/nodes/us-server", headers=hdr)
    assert r.status_code == 200
    n = r.json()
    for f in ("id", "name", "role", "health", "stale", "source"):
        assert f in n, f"missing contract field {f}"
    assert n["role"] in ("PRIMARY", "STANDBY_GATEWAY", "RELAY", "EXISTING_BUSINESS", "WORKER")
    assert n["health"] in ("healthy", "degraded", "offline", "unknown")
    assert isinstance(n["stale"], bool)


def test_resource_shape_and_kind_filter(client, hdr):
    r = client.get("/api/v1/resources?kind=service", headers=hdr)
    assert r.status_code == 200
    items = r.json()["items"]
    assert items and all(i["kind"] == "service" for i in items)
    for i in items[:3]:
        for f in ("id", "kind", "owner_system", "display_name", "health", "stale", "source"):
            assert f in i


def test_services_alias_equals_kind_service(client, hdr):
    a = client.get("/api/v1/services", headers=hdr).json()["items"]
    b = client.get("/api/v1/resources?kind=service", headers=hdr).json()["items"]
    assert {i["id"] for i in a} == {i["id"] for i in b}


def test_agent_shape(client, hdr):
    r = client.get("/api/v1/agents/agent.rakazo.chief", headers=hdr)
    assert r.status_code == 200
    a = r.json()
    for f in ("id", "display_name", "owner_system", "status", "capabilities", "observed_at"):
        assert f in a
    assert a["status"] in ("available", "degraded", "offline", "unknown")


def test_capabilities_readonly_disabled(client, hdr):
    caps = client.get("/api/v1/capabilities", headers=hdr).json()["items"]
    names = {c["name"] for c in caps}
    assert "probe.http.get" in names and "task.shell.exec" in names
    for c in caps:
        assert c["risk"] in ("READ", "LOW", "MEDIUM", "HIGH", "CRITICAL")
        if c["risk"] in ("HIGH", "CRITICAL"):
            assert c["enabled"] is False, "SQL 约束：HIGH/CRITICAL 不得启用"


# ---- provenance / UNKNOWN / STALE ----

def test_no_probe_evidence_means_unknown(client, hdr):
    """审计基线无实时探针 → 全部 health=unknown（不得伪造 healthy）。"""
    for n in client.get("/api/v1/nodes", headers=hdr).json()["items"]:
        assert n["health"] == "unknown"
        assert n["source_system"].startswith("audit:")
        assert n["observed_at"] is not None
        assert "ttl_seconds" in n and "received_at" in n


def test_stale_decay_after_ttl(client, hdr):
    """ttl 过期 → stale=true（假时钟注入验证衰减规则）。"""
    store = app_mod._store
    import datetime as dt
    old = dt.datetime.fromisoformat("2026-11-08T15:00:00+08:00")
    future = old.timestamp() + 86400 + 10  # 审计时点 + 24h10s
    store.clock = lambda: future
    try:
        n = client.get("/api/v1/nodes/mac-mini", headers=hdr).json()
        assert n["stale"] is True
    finally:
        store.clock = time.time


# ---- 分页 ----

def test_pagination_cursor(client, hdr):
    r1 = client.get("/api/v1/nodes?limit=2", headers=hdr).json()
    assert len(r1["items"]) == 2 and r1["next_cursor"]
    r2 = client.get(f"/api/v1/nodes?limit=2&cursor={r1['next_cursor']}", headers=hdr).json()
    assert {i["id"] for i in r1["items"]} and {i["id"] for i in r2["items"]}
    assert not ({i["id"] for i in r1["items"]} & {i["id"] for i in r2["items"]})


def test_unknown_agent_404(client, hdr):
    assert client.get("/api/v1/agents/agent.nope", headers=hdr).status_code == 404


# ---- P1-05 第二轮补测（评审 R2 §4）----

def test_observed_vs_received_distinct_for_snapshot(client, hdr):
    """审计快照：observed_at=证据时间(15:00)，received_at=实际装载时刻——必须可区分。"""
    n = client.get("/api/v1/nodes/mac-mini", headers=hdr).json()
    assert n["observed_at"] == "2026-11-08T15:00:00+08:00"  # 原始证据时间
    assert n["received_at"] != n["observed_at"], "received_at 不得与 observed_at 填同一值"
    assert n["received_at"] > "2026-11-08T07:00:00+00:00"  # 装载时刻晚于审计证据时刻(07:00Z)
