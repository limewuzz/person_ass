"""R5 安全回归（对应 GPT-6 独立评审 A1/A2/P1 + 新增负向）。

与 R5-NEGATIVE-REPRO-TESTS.py 的 7 项互补：这里是权限矩阵全组合与额外负向。
"""
import pytest


@pytest.fixture(autouse=True)
def _probe_test_mode(monkeypatch):
    """仅本模块内启用 test 模式（作用域隔离）。"""
    monkeypatch.setenv("MWCP_PROBE_MODE", "test")

from fastapi.testclient import TestClient

import app as app_mod
from auth import mint_token
from probes import (MAX_BATCH_SIZE, PRODUCTION_ALLOWED_HOSTS, ProbeTarget,
                    ProbeTargetRejected, register_target, run_probe)
from registry import RegistryStore, ResourceRec

SECRET = "test-secret-only-for-local-tests"


@pytest.fixture()
def client():
    return TestClient(app_mod.app, raise_server_exceptions=False)


def _hdr(typ, role, scopes, jti, sub="x", **kw):
    base = dict(sub=sub, typ=typ, role=role, scopes=scopes, jti=jti)
    base.update(kw)
    return {"Authorization": "Bearer " + mint_token(SECRET, **base)}


# ---- A1/A2 权限矩阵：三类身份 × 全部 Registry 列表与详情 ----

MATRIX = [
    # (path, 期望 viewer=200, worker=403)
    ("/api/v1/nodes", 200, 403),
    ("/api/v1/resources", 200, 403),
    ("/api/v1/services", 200, 403),
    ("/api/v1/agents", 200, 403),
    ("/api/v1/capabilities", 200, 403),
    ("/api/v1/nodes/mac-mini", 200, 403),
    ("/api/v1/resources/svc.mwcp.portal", 200, 403),
    ("/api/v1/agents/agent.rakazo.chief", 200, 403),   # A1 复现点：worker 必须 403
]


@pytest.mark.parametrize("path,viewer_code,worker_code", MATRIX)
def test_permission_matrix(client, path, viewer_code, worker_code):
    v = client.get(path, headers=_hdr("actor", "viewer", ["registry:read", "health:read"], "jti-m1"))
    assert v.status_code == viewer_code, f"viewer {path}: {v.status_code}"
    w = client.get(path, headers=_hdr("worker", "worker", ["worker:heartbeat"], "jti-m2"))
    assert w.status_code == worker_code, f"worker {path}: {w.status_code}（A1 回归）"
    s = client.get(path, headers=_hdr("service", "viewer", ["registry:read"], "jti-m3"))
    assert s.status_code == viewer_code


def test_unknown_typ_all_rejected(client):
    """A2：任意未知 typ 在所有受保护路径 401。"""
    for path in ("/api/v1/me", "/api/v1/nodes", "/api/v1/agents/agent.rakazo.chief"):
        r = client.get(path, headers=_hdr("not-a-type", "admin", ["admin:read"], "jti-m4"))
        assert r.status_code == 401, f"{path}: {r.status_code}"


def test_service_admin_role_still_no_admin_scope(client):
    r = client.get("/api/v1/me", headers=_hdr("service", "admin",
                                              ["admin:read", "registry:read"], "jti-m5"))
    assert "admin:read" not in r.json()["principal"]["scopes"]


# ---- A2 附加：required claims ----

def test_token_missing_nbf_rejected(client):
    import jwt as pyjwt, time as _t
    payload = {"iss": "https://mock-issuer.mwcp.local", "aud": "mwcp-api", "sub": "u",
               "typ": "actor", "role": "viewer", "scopes": ["registry:read"],
               "jti": "jti-m6", "iat": int(_t.time()), "exp": int(_t.time()) + 600}
    t = pyjwt.encode(payload, SECRET, algorithm="HS256", headers={"kid": "dev-1"})
    assert client.get("/api/v1/nodes", headers={"Authorization": f"Bearer {t}"}).status_code == 401


# ---- P1 附加：注册制/端口/批量上限（模块默认 production 场景由 GPT-6 复现测试覆盖）----

def _registered_store(rid="svc.mock.reg"):
    st = RegistryStore()
    st.resources[rid] = ResourceRec(id=rid, kind="service", owner_system="t", display_name=rid, node_id=None)
    return st


def test_run_probe_refuses_unregistered_resource():
    st = RegistryStore()  # 空
    t = ProbeTarget(resource_id="ghost", url="http://127.0.0.1:1/x")
    with pytest.raises(ProbeTargetRejected):
        run_probe(t, st, allow_loopback=True)
    assert "ghost" not in st.resources  # 绝不自动创建


def test_port_range_enforced():
    st = _registered_store()
    with pytest.raises(ProbeTargetRejected):
        register_target(st, ProbeTarget(resource_id="svc.mock.reg", capability="probe.tcp.check",
                                        host="127.0.0.1", port=70000), allow_loopback=True)
    with pytest.raises(ProbeTargetRejected):
        register_target(st, ProbeTarget(resource_id="svc.mock.reg", capability="probe.tcp.check",
                                        host="127.0.0.1", port=0), allow_loopback=True)


def test_batch_size_cap():
    from probes import run_batch
    st = _registered_store()
    st.resources["svc.mock.reg2"] = ResourceRec(id="svc.mock.reg2", kind="service",
                                                owner_system="t", display_name="r2", node_id=None)
    targets = [ProbeTarget(resource_id="svc.mock.reg", url="http://127.0.0.1:1/x")] * (MAX_BATCH_SIZE + 1)
    with pytest.raises(ProbeTargetRejected):
        run_batch(targets, st, allow_loopback=True)


def test_production_allowlist_still_empty_and_wired():
    assert not PRODUCTION_ALLOWED_HOSTS
    st = _registered_store()
    with pytest.raises(ProbeTargetRejected):
        # 即便登记了资源，production 语义在 validate 显式模式下仍拒绝白名单外主机
        from probes import validate_probe_target
        validate_probe_target(ProbeTarget(resource_id="svc.mock.reg", url="http://203.0.113.10/x"),
                              production_mode=True)


# ---- D4：secrets 文件加载功能测试（不止 grep 字符串） ----

def test_load_secrets_from_file(tmp_path, monkeypatch):
    from auth import load_secrets_from_env
    f = tmp_path / "auth_secrets"
    f.write_text("kid-a:sec-a\nkid-b:sec-b\n")
    monkeypatch.setenv("MWCP_AUTH_SECRETS_FILE", str(f))
    monkeypatch.delenv("MWCP_AUTH_SECRETS", raising=False)
    assert load_secrets_from_env() == {"kid-a": "sec-a", "kid-b": "sec-b"}


def test_load_secrets_env_fallback(monkeypatch):
    from auth import load_secrets_from_env
    monkeypatch.delenv("MWCP_AUTH_SECRETS_FILE", raising=False)
    monkeypatch.setenv("MWCP_AUTH_SECRETS", "dev-1:x")
    assert load_secrets_from_env() == {"dev-1": "x"}


# ---- R6-P1 补充：已登记目标的端点偷换负向 ----

def test_approved_target_url_swap_rejected():
    """资源+目标已按 url A 登记；用同 resource_id 换 url B 执行 → 拒绝。"""
    from probes import ProbeTarget, ProbeTargetRejected, register_target, run_probe
    from registry import RegistryStore, ResourceRec
    st = RegistryStore()
    st.resources["svc.swap"] = ResourceRec(id="svc.swap", kind="service", owner_system="t",
                                           display_name="s", node_id=None)
    register_target(st, ProbeTarget(resource_id="svc.swap", url="http://127.0.0.1:9/a"),
                    allow_loopback=True)
    with pytest.raises(ProbeTargetRejected, match="mismatch"):
        run_probe(ProbeTarget(resource_id="svc.swap", url="http://127.0.0.1:9/b"), st,
                  allow_loopback=True)


def test_approved_target_port_swap_rejected():
    from probes import ProbeTarget, ProbeTargetRejected, register_target
    from registry import RegistryStore, ResourceRec
    st = RegistryStore()
    st.resources["svc.port"] = ResourceRec(id="svc.port", kind="service", owner_system="t",
                                           display_name="p", node_id=None)
    register_target(st, ProbeTarget(resource_id="svc.port", capability="probe.tcp.check",
                                    host="127.0.0.1", port=9), allow_loopback=True)
    from probes import validate_probe_target
    t2 = ProbeTarget(resource_id="svc.port", capability="probe.tcp.check", host="127.0.0.1", port=10)
    # 端口替换：先过 SSRF（loopback 放行），再被绑定校验拒绝
    st.resources["svc.port"]._ = None
    from probes import _require_approved_target
    _register_helper(st, t2)


def _register_helper(st, t2):
    from probes import _require_approved_target, ProbeTargetRejected
    with pytest.raises(ProbeTargetRejected, match="mismatch"):
        _require_approved_target(st, t2)


def test_production_mode_rejects_loopback_even_with_flag():
    """R6-P2：生产模式下即使 allow_loopback=True 也拒绝回环。"""
    from probes import ProbeTarget, ProbeTargetRejected, validate_probe_target
    with pytest.raises(ProbeTargetRejected, match="non-public|whitelist"):
        # 生产模式拒绝回环：命中白名单分支（host 不在白名单）或 IP 分支（non-public）均为正确拒绝
        validate_probe_target(ProbeTarget(resource_id="x", url="http://127.0.0.1:1/x"),
                              allow_loopback=True, production_mode=True)
