"""健康端点契约测试（含 P0 评审 §B 的 readiness 503 语义修正）。"""
from fastapi.testclient import TestClient

import app as app_mod
from auth import mint_token

SECRET = "test-secret-only-for-local-tests"
client = TestClient(app_mod.app, raise_server_exceptions=False)


def test_health_live_200_open_access():
    r = client.get("/api/v1/health/live")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and "uptime_seconds" in body


def test_health_ready_503_when_deps_not_connected():
    """必要依赖未连接 → 503 + dependency_status，绝不 HTTP 200 冒充 ready。"""
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 503, "database/probes 未接入时必须 503"
    body = r.json()
    assert body["status"] == "not_ready"
    ds = body["dependency_status"]
    assert ds["database"] == "not_connected"
    assert ds["probes"] == "not_configured"
    assert ds["auth"] in ("ok", "misconfigured")


def test_health_ready_open_access():
    """健康探针免认证（评审 §C：独立健康探针允许未认证访问）。"""
    assert client.get("/api/v1/health/ready").status_code in (200, 503)


def test_registry_requires_auth():
    assert client.get("/api/v1/nodes").status_code == 401


def test_unknown_route_404():
    t = mint_token(SECRET, sub="u1", typ="actor", role="viewer",
                   scopes=["registry:read"], jti="jti-404")
    r = client.get("/api/v1/tasks", headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 404  # P1-08 才实现
