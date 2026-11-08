"""P1-04 认证矩阵测试（401/403/IDOR/重放/日志安全）。

对应评审 §C 必测项：缺失令牌 401、无权动作 403、无权跨资源查询、错误 issuer/aud/alg、
过期、重放（吊销）、scope 缺失、日志不泄露 token。
"""
import logging

import pytest
from fastapi.testclient import TestClient

import app as app_mod
from auth import mint_token

SECRET = "test-secret-only-for-local-tests"


@pytest.fixture()
def client():
    return TestClient(app_mod.app, raise_server_exceptions=False)


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def viewer_token(**kw) -> str:
    base = dict(sub="u1", typ="actor", role="viewer",
                scopes=["health:read", "registry:read"], jti="jti-viewer")
    base.update(kw)
    return mint_token(SECRET, **base)


# ---- 401 族 ----

def test_missing_token_401(client):
    assert client.get("/api/v1/nodes").status_code == 401


def test_expired_token_401(client):
    t = viewer_token(jti="jti-exp", ttl_seconds=-10)
    assert client.get("/api/v1/nodes", headers=_hdr(t)).status_code == 401


def test_bad_signature_401(client):
    t = mint_token("wrong-secret", sub="u1", typ="actor", role="viewer",
                   scopes=["registry:read"], jti="jti-badsig")
    assert client.get("/api/v1/nodes", headers=_hdr(t)).status_code == 401


def test_wrong_issuer_401(client):
    t = viewer_token(jti="jti-iss", issuer="https://evil.example")
    assert client.get("/api/v1/nodes", headers=_hdr(t)).status_code == 401


def test_wrong_audience_401(client):
    t = viewer_token(jti="jti-aud", aud="other-api")
    assert client.get("/api/v1/nodes", headers=_hdr(t)).status_code == 401


def test_alg_none_rejected_401(client):
    import jwt as pyjwt
    import time as _t
    payload = {"iss": "https://mock-issuer.mwcp.local", "aud": "mwcp-api", "sub": "u1",
               "typ": "actor", "role": "viewer", "scopes": ["registry:read"],
               "jti": "jti-none", "exp": int(_t.time()) + 600}
    none_jwt = pyjwt.encode(payload, key="", algorithm="none")
    assert client.get("/api/v1/nodes", headers=_hdr(none_jwt)).status_code == 401


def test_unknown_kid_401(client):
    t = viewer_token(jti="jti-kid", kid="nonexistent-kid")
    assert client.get("/api/v1/nodes", headers=_hdr(t)).status_code == 401


def test_revoked_token_replay_401(client):
    t = viewer_token(jti="jti-replay")
    app_mod._validator.revocations.revoke("jti-replay")
    assert client.get("/api/v1/nodes", headers=_hdr(t)).status_code == 401


# ---- 403 / 对象级（IDOR）----

def test_scope_missing_403(client):
    t = mint_token(SECRET, sub="u1", typ="actor", role="viewer", scopes=[], jti="jti-noscope")
    assert client.get("/api/v1/nodes", headers=_hdr(t)).status_code == 403


def test_worker_cannot_read_registry_403(client):
    t = mint_token(SECTOR := SECRET, sub="w1", typ="worker", role="worker",
                   scopes=["worker:heartbeat"], jti="jti-worker")
    assert client.get("/api/v1/nodes", headers=_hdr(t)).status_code == 403


def test_node_scoped_token_idor_403(client):
    """token 只授权 mac-mini：访问 us-server 节点详情必须 403（对象级授权）。"""
    t = viewer_token(jti="jti-node", node_ids=["mac-mini"])
    assert client.get("/api/v1/nodes/mac-mini", headers=_hdr(t)).status_code == 200
    r = client.get("/api/v1/nodes/us-server", headers=_hdr(t))
    assert r.status_code == 403
    # 列表同样不得泄露越权对象
    ids = [i["id"] for i in client.get("/api/v1/nodes", headers=_hdr(t)).json()["items"]]
    assert ids == ["mac-mini"]


def test_kind_scoped_token_idor_403(client):
    t = viewer_token(jti="jti-kind", kinds=["service"])
    assert client.get("/api/v1/resources?kind=service", headers=_hdr(t)).status_code == 200
    r = client.get("/api/v1/resources?kind=agent", headers=_hdr(t))
    assert r.status_code == 403


def test_unknown_node_404(client):
    t = viewer_token(jti="jti-404")
    assert client.get("/api/v1/nodes/no-such-node", headers=_hdr(t)).status_code == 404


# ---- 日志安全 ----

def test_token_never_logged(caplog, client):
    t = viewer_token(jti="jti-log")
    with caplog.at_level(logging.DEBUG, logger="uvicorn.access"):
        client.get("/api/v1/nodes", headers=_hdr(t))
        client.get("/api/v1/nodes", headers=_hdr(t + "tampered"))
    for record in caplog.records:
        assert SECRET not in record.getMessage()
        assert t not in record.getMessage(), "raw token leaked into logs"


# ---- /me ----

def test_me_returns_principal(client):
    t = viewer_token(jti="jti-me", node_ids=["mac-mini"])
    r = client.get("/api/v1/me", headers=_hdr(t))
    assert r.status_code == 200
    body = r.json()["principal"]
    assert body["sub"] == "u1" and body["role"] == "viewer"
    assert body["node_scope"] == ["mac-mini"]
    assert "registry:read" in body["scopes"]


def test_nbf_future_token_401(client):
    t = viewer_token(jti="jti-nbf", nbf_offset=3600)
    assert client.get("/api/v1/nodes", headers=_hdr(t)).status_code == 401
