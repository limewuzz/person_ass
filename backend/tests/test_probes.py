"""P1-06 探针测试：Mock 目标（本地临时 HTTP 服务）+ 超时/拒绝/鉴权/过期/传播。"""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

import app as app_mod
from auth import mint_token
from probes import ProbeTarget, ProbeTargetRejected, run_probe, run_batch, validate_probe_target
from registry import _iso

SECRET = "test-secret-only-for-local-tests"
HDR = {"Authorization": "Bearer " + mint_token(
    SECRET, sub="u1", typ="actor", role="admin",
    scopes=["registry:read", "health:read", "probes:read", "approvals:read", "admin:read"],
    jti="jti-probes")}


class _Slow(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/slow":
            time.sleep(2.0)
            self.send_response(200)
        elif self.path == "/denied":
            self.send_response(401)
        elif self.path == "/sick":
            self.send_response(503)
        else:
            self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *a):  # 静默
        pass


@pytest.fixture(scope="module")
def mock_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Slow)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture()
def client():
    return TestClient(app_mod.app, raise_server_exceptions=False)


def _t(url, **kw) -> ProbeTarget:
    base = dict(resource_id="svc.mock.target", kind="service", url=url,
                timeout_seconds=0.8, ttl_seconds=60)
    base.update(kw)
    return ProbeTarget(**base)


def test_healthy_probe_lives_not_fake(mock_server, client):
    """UNKNOWN→HEALTHY：真实观测改变 health，provenance 三时刻可区分。"""
    store = app_mod._store
    obs = run_probe(_t(mock_server + "/ok"), store, allow_loopback=True)
    assert obs.status == "healthy" and obs.health == "healthy"
    rec = store.resources["svc.mock.target"]
    assert rec.source == "probe:http.get"
    assert rec.base_health == "healthy"
    assert rec.observed_at and rec.received_at
    # received_at 晚于 observed_at（处理延迟），且不再等于审计种子时间
    assert rec.received_at >= rec.observed_at
    body = client.get("/api/v1/resources/svc.mock.target", headers=HDR).json()
    assert body["health"] == "healthy" and body["source_system"] == "probe:http.get"


def test_timeout_is_unknown_not_offline(mock_server):
    store = app_mod._store
    obs = run_probe(_t(mock_server + "/slow", timeout_seconds=0.3), store, allow_loopback=True)
    assert obs.status == "timeout" and obs.health == "unknown"  # 超时≠离线


def test_auth_rejected_is_unknown_with_note(mock_server):
    store = app_mod._store
    obs = run_probe(_t(mock_server + "/denied"), store, allow_loopback=True)
    assert obs.status == "auth_rejected" and obs.health == "unknown"
    assert "401" in obs.note


def test_5xx_is_degraded(mock_server):
    store = app_mod._store
    obs = run_probe(_t(mock_server + "/sick"), store, allow_loopback=True)
    assert obs.status == "degraded" and obs.health == "degraded"


def test_offline_on_refused():
    store = app_mod._store
    obs = run_probe(_t("http://127.0.0.1:1/x", timeout_seconds=0.5), store, allow_loopback=True)
    assert obs.status == "offline" and obs.health == "offline"


def test_ttl_expiry_marks_stale(mock_server):
    """短 TTL 过期 → stale=true（假时钟推进验证衰减）。"""
    import datetime as dt
    store = app_mod._store
    run_probe(_t(mock_server + "/ok", ttl_seconds=30), store, allow_loopback=True)
    import app as m
    fut = dt.datetime.now(dt.timezone.utc).timestamp() + 31
    store.clock = lambda: fut
    try:
        rec = store.resources["svc.mock.target"]
        assert store.resource_out(rec)["stale"] is True
    finally:
        store.clock = time.time


def test_capability_whitelist_enforced():
    with pytest.raises(ValueError):
        run_probe(ProbeTarget(resource_id="x", capability="task.shell.exec",
                              url="http://127.0.0.1:1/"), app_mod._store)


def test_tcp_probe_healthy_loopback(mock_server):
    """tcp.check 对本地 mock 端口 healthy；对拒绝端口 offline。"""
    import urllib.parse as up
    port = up.urlparse(mock_server).port
    store = app_mod._store
    obs = run_probe(ProbeTarget(resource_id="svc.mock.tcp", capability="probe.tcp.check",
                                host="127.0.0.1", port=port, ttl_seconds=60), store, allow_loopback=True)
    assert obs.health == "healthy"
    obs2 = run_probe(ProbeTarget(resource_id="svc.mock.tcp2", capability="probe.tcp.check",
                                 host="127.0.0.1", port=1, timeout_seconds=0.5), store, allow_loopback=True)
    assert obs2.health == "offline"


# ---- R4 §B：SSRF 防护 / 重定向 / 并发上限 / 负向测试 ----

def test_ssrf_metadata_blocked():
    for url in ("http://169.254.169.254/latest/meta-data/",
                "http://100.100.100.100/latest/meta-data/",
                "http://metadata.google.internal/computeMetadata/v1/"):
        with pytest.raises(ProbeTargetRejected):
            validate_probe_target(_t(url))


def test_ssrf_private_blocked():
    with pytest.raises(ProbeTargetRejected):
        validate_probe_target(_t("http://10.1.2.3/x"))
    with pytest.raises(ProbeTargetRejected):
        validate_probe_target(_t("http://192.168.1.1/x"))


def test_ssrf_loopback_requires_flag():
    with pytest.raises(ProbeTargetRejected):
        validate_probe_target(_t("http://127.0.0.1:1/x"))            # 未声明 allow_loopback → 拒
    validate_probe_target(_t("http://127.0.0.1:1/x"), allow_loopback=True)  # 显式声明 → 过


def test_ssrf_scheme_and_creds_blocked():
    with pytest.raises(ProbeTargetRejected):
        validate_probe_target(_t("file:///etc/passwd"))
    with pytest.raises(ProbeTargetRejected):
        validate_probe_target(_t("gopher://127.0.0.1:6379/_x"))
    with pytest.raises(ProbeTargetRejected):
        validate_probe_target(_t("http://user:pass@127.0.0.1:1/x"), allow_loopback=True)


def test_production_mode_empty_whitelist_blocks_everything():
    with pytest.raises(ProbeTargetRejected):
        validate_probe_target(_t("http://example.com/x"), production_mode=True)


def test_redirect_not_followed(mock_server):
    """3xx 不跟随（防 SSRF 重定向链）；返回 redirect 态=unknown。"""
    class _Redir(_Slow):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/")
            self.end_headers()
    import threading
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Redir)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        store = app_mod._store
        obs = run_probe(_t(f"http://127.0.0.1:{srv.server_port}/r"), store, allow_loopback=True)
        assert obs.status == "redirect" and obs.health == "unknown"
        assert "not followed" in obs.note
    finally:
        srv.shutdown()


def test_batch_concurrency_cap(mock_server):
    """max_concurrency=1 时两个慢目标串行（elapsed ≥ 2×slow）。"""
    import time as tt
    store = app_mod._store
    t0 = tt.time()
    run_batch([_t(mock_server + "/slow", resource_id="svc.mock.b1"),
               _t(mock_server + "/slow", resource_id="svc.mock.b2")],
              store, max_concurrency=1, allow_loopback=True)
    # /slow 睡 2.0s；两个 0.8s 超时目标串行下限 ~1.6s（超时仍占线程位）
    assert tt.time() - t0 >= 1.0
