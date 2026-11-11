"""RC 查询端点：形状/鉴权/source_meta 语义/SSE/attempts + fixtures 快照生成。"""

import json
import os
import pathlib
import pytest
from fastapi.testclient import TestClient

import app as app_mod
from auth import mint_token

SECRET = "test-secret-only-for-local-tests"
FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "contracts" / "mock-fixtures"


def _hdr(typ="actor", role="admin", scopes=None, jti="q", sub="admin-1"):
    default = [
        "registry:read",
        "health:read",
        "probes:read",
        "approvals:read",
        "approvals:decide",
        "admin:read",
        "tasks:read",
        "tasks:write",
    ]
    return {
        "Authorization": "Bearer "
        + mint_token(
            SECRET,
            sub=sub,
            typ=typ,
            role=role,
            scopes=scopes if scopes is not None else default,
            jti=jti,
        )
    }


@pytest.fixture()
def client():
    return TestClient(app_mod.app, raise_server_exceptions=False)


def test_ui_bootstrap_shape(client):
    r = client.get("/api/v1/ui/bootstrap", headers=_hdr())
    assert r.status_code == 200
    b = r.json()
    assert (
        b["app_mode"] == "LOCAL_MOCK"
        and b["contract_version"] == "3.0.0-fanout-local"
    )
    assert b["login"]["sub"] == "admin-1"
    fs = b["features"]
    assert fs["real_probes"]["status"] == "DISABLED"  # 白名单空=by design
    assert fs["production_db"]["status"] == "DISABLED"  # PG NOT RUN 诚实
    assert fs["cherry_links"]["status"] == "MOCK_ONLY"


def test_dashboard_summary_counts_and_null_semantics(client):
    token = _hdr()
    client.post(
        "/api/v1/work-items", json={"title": "t", "kind": "task"}, headers=token
    )
    r = client.get("/api/v1/dashboard/summary", headers=token)
    assert r.status_code == 200
    d = r.json()
    for k in ("queued", "running", "succeeded", "failed", "waiting_approval"):
        assert d["task_counts"][k] >= 0
    assert d["source_meta"]["kind"] == "mock"
    # 未接真实探针：节点健康必须 unknown（不得 fake healthy）
    assert all(n["health"] == "unknown" for n in d["nodes"]["items"])


DISPLAY_DOMAINS = [
    "/api/v1/workflows",
    "/api/v1/network/links",
    "/api/v1/models",
    "/api/v1/projects",
    "/api/v1/compute/runs",
    "/api/v1/knowledge",
]


@pytest.mark.parametrize("path", DISPLAY_DOMAINS)
def test_display_domains_shape_and_meta(client, path):
    r = client.get(path, headers=_hdr())
    assert r.status_code == 200
    d = r.json()
    assert set(d) >= {"items", "next_cursor", "source_meta"}
    for it in d["items"]:
        for f in ("id", "title", "source_meta", "enabled"):
            assert f in it
        assert it["source_meta"]["kind"] in ("mock", "unavailable", "live")
        if it["source_meta"]["kind"] != "live":
            assert it["enabled"] is False, "无证据的域不得 enabled"


def test_compute_and_knowledge_explicitly_unavailable(client):
    for p in ("/api/v1/compute/runs",):
        d = client.get(p, headers=_hdr()).json()
        assert any(i["source_meta"]["kind"] == "unavailable" for i in d["items"])


def test_events_history_pagination_and_sse(client):
    token = _hdr()
    client.post(
        "/api/v1/work-items", json={"title": "a", "kind": "task"}, headers=token
    )
    client.post(
        "/api/v1/work-items", json={"title": "b", "kind": "task"}, headers=token
    )
    h = client.get("/api/v1/events/history?limit=1", headers=token).json()
    assert len(h["items"]) == 1 and h["next_cursor"]
    h2 = client.get(
        f"/api/v1/events/history?limit=10&cursor={h['next_cursor']}", headers=token
    ).json()
    assert h2["items"] and h2["items"][0]["id"] != h["items"][0]["id"]
    # SSE：content-type + 事件重放
    with client.stream("GET", "/api/v1/events", headers=token) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        chunk = b""
        for piece in resp.iter_raw():
            chunk += piece
            if b"event: audit" in chunk:
                break
    assert b"event: audit" in chunk


def test_task_flow_via_api_end_to_end(client):
    token = _hdr()
    wi = client.post(
        "/api/v1/work-items", json={"title": "RC e2e", "kind": "task"}, headers=token
    )
    assert wi.status_code == 201
    body = {
        "capability": "local.simulate",
        "resource_id": "local-ledger",
        "arguments": {},
        "work_item_id": wi.json()["id"],
        "dry_run": True,
        "origin": {"channel": "web"},
    }
    headers = {**token, "Idempotency-Key": "rc-e2e-00000001"}
    tk = client.post("/api/v1/tasks", headers=headers, json=body)
    assert tk.status_code == 202 and tk.json()["state"] == "WAITING_APPROVAL"
    tid = tk.json()["task_id"]
    replay = client.post("/api/v1/tasks", headers=headers, json=body)
    assert (
        replay.status_code == 202
        and replay.json()["replayed"] is True
        and replay.json()["task_id"] == tid
    )
    events = client.get(f"/api/v1/tasks/{tid}/events", headers=token).json()
    assert events["items"][0]["kind"] == "created"
    canceled = client.post(f"/api/v1/tasks/{tid}/cancel", headers=token)
    assert canceled.status_code == 202 and canceled.json()["state"] == "CANCELED"
    hi = client.post(
        "/api/v1/tasks",
        headers={**token, "Idempotency-Key": "rc-high-00000001"},
        json={**body, "risk": "HIGH"},
    )
    assert hi.status_code == 403 and hi.json()["error"]["code"] == "risk_blocked"
    attempts = client.get(f"/api/v1/tasks/{tid}/attempts", headers=token)
    assert attempts.status_code == 200 and attempts.json()["items"] == []


def test_new_endpoints_auth_matrix(client):
    protected = [
        "/api/v1/ui/bootstrap",
        "/api/v1/dashboard/summary",
        "/api/v1/events/history",
        "/api/v1/workflows",
        "/api/v1/knowledge",
        "/api/v1/audit",
    ]
    for p in protected:
        assert client.get(p).status_code == 401, p
    # viewer 无 admin:read → /audit 403；worker 无 tasks:read → history 403
    v = _hdr(role="viewer", scopes=["registry:read", "tasks:read"])
    assert client.get("/api/v1/audit", headers=v).status_code == 403
    w = _hdr(typ="worker", role="worker", scopes=["worker:heartbeat"], sub="w9")
    assert client.get("/api/v1/events/history", headers=w).status_code == 403


def test_worker_path_must_match_subject_via_api(client):
    w = _hdr(typ="worker", role="worker", scopes=["worker:heartbeat"], sub="w-real")
    other = client.post(
        "/api/v1/workers/w-forged/heartbeat",
        headers=w,
        json={
            "node_id": "n",
            "version": "1",
            "available_capabilities": [],
            "observed_at": "2026-11-08T00:00:00Z",
        },
    )
    assert other.status_code == 403
    ok = client.post(
        "/api/v1/workers/w-real/heartbeat",
        headers=w,
        json={
            "node_id": "n",
            "version": "1",
            "available_capabilities": [],
            "observed_at": "2026-11-08T00:00:00Z",
        },
    )
    assert ok.status_code == 200


def test_generate_contract_fixtures(client, tmp_path):
    FIXTURES = tmp_path / "actual-response-snapshots"
    """把真实响应快照写进 contracts/mock-fixtures/（Codex 的响应样本来源）。"""
    token = _hdr()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    snap = {}
    for name, p in [
        ("ui-bootstrap", "/api/v1/ui/bootstrap"),
        ("dashboard-summary", "/api/v1/dashboard/summary"),
        ("events-history", "/api/v1/events/history?limit=5"),
        ("workflows", "/api/v1/workflows"),
        ("models", "/api/v1/models"),
        ("nodes", "/api/v1/nodes?limit=2"),
        ("integrations", "/api/v1/integrations"),
        ("artifacts", "/api/v1/artifacts"),
    ]:
        rr = client.get(p, headers=token)
        assert rr.status_code == 200, (name, rr.status_code, rr.text[:120])
        snap[name] = rr.json()
    for name, body in snap.items():
        (FIXTURES / f"{name}.json").write_text(
            json.dumps(body, ensure_ascii=False, indent=2) + "\n"
        )
    assert (FIXTURES / "ui-bootstrap.json").exists()
