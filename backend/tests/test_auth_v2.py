"""P1-04 第二轮补测（评审 R2 §3）：Service 身份硬边界、worker path 匹配、fail-closed。"""
import pytest
from fastapi.testclient import TestClient

import app as app_mod
from auth import mint_token, require_worker_path_match
from auth import Principal

SECRET = "test-secret-only-for-local-tests"


@pytest.fixture()
def client():
    return TestClient(app_mod.app, raise_server_exceptions=False)


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


def test_service_cannot_get_admin_scope_even_if_claimed(client):
    """service 身份即使 token 声称 admin:read，decode 时也被强制剥离。"""
    t = mint_token(SECRET, sub="svc1", typ="service", role="admin",
                   scopes=["admin:read", "registry:read", "health:read",
                           "probes:read", "approvals:read"], jti="jti-svc-admin")
    r = client.get("/api/v1/me", headers=_hdr(t))
    assert r.status_code == 200
    p = r.json()["principal"]
    assert p["type"] == "service"
    assert "admin:read" not in p["scopes"], "service 必须拿不到 admin:read"
    assert "registry:read" in p["scopes"]  # 正常读权限保留


def test_service_normal_viewer_works(client):
    t = mint_token(SECRET, sub="svc2", typ="service", role="viewer",
                   scopes=["registry:read"], jti="jti-svc-view")
    assert client.get("/api/v1/nodes", headers=_hdr(t)).status_code == 200


def test_worker_path_id_must_match_subject():
    """Worker 协议端点：path id != token subject → 403（P1-07 端点将统一调用）。"""
    w = Principal(sub="worker-a", typ="worker", role="worker",
                  scopes={"worker:heartbeat"}, jti="x")
    require_worker_path_match(w, "worker-a")  # 匹配：不抛
    with pytest.raises(Exception) as e:
        require_worker_path_match(w, "worker-b")
    assert e.value.status_code == 403
    human = Principal(sub="u1", typ="actor", role="admin", scopes={"admin:read"}, jti="y")
    with pytest.raises(Exception):
        require_worker_path_match(human, "u1")  # 非 worker 身份也不许走 worker 端点


def test_fail_closed_when_auth_config_missing(monkeypatch):
    """MWCP_AUTH_SECRETS 缺失 → 受保护路径 503（真实中间件行为，非 TestClient 绕过）。"""
    monkeypatch.setattr(app_mod, "_validator", None)
    c = TestClient(app_mod.app, raise_server_exceptions=False)
    r = c.get("/api/v1/nodes", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "auth_misconfigured"
    # 健康探针仍可用
    assert c.get("/api/v1/health/live").status_code == 200
    ready = c.get("/api/v1/health/ready")
    assert ready.status_code == 503
    assert ready.json()["dependency_status"]["auth"] == "misconfigured"
