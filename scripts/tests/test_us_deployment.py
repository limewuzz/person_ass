"""A SPA's successful HTTP status must never satisfy deployment checks."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sys
from threading import Thread

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("us_check", ROOT / "scripts/check_us_deployment.py")
doctor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = doctor
SPEC.loader.exec_module(doctor)
ORIGIN = "https://magicworkshop.fun"
COMMIT = "a" * 40
SHA = json.loads((ROOT / "contracts/CONTRACT-LOCK.json").read_text())["sha256"]


@pytest.fixture
def routes():
    def html(prefix):
        return (f'<script type="module" src="{prefix}app.js"></script>'
                f'<link rel="stylesheet" href="{prefix}app.css">').encode()

    metadata = {"head": COMMIT, "mode": "session", "public_origin": ORIGIN,
                "read_only": True, "web_base": "/workshop/", "contract_sha256": SHA}
    data = {
        "/": (200, "text/html", html("/portal-assets/")),
        "/workshop/": (200, "text/html", html("/workshop/assets/")),
        "/workshop/build-meta.json": (200, "application/json", json.dumps(metadata).encode()),
        "/api/v1/me": (401, "application/json", b'{"error":"unauthorized"}'),
    }
    for prefix in ["/portal-assets/", "/workshop/assets/"]:
        data[prefix + "app.js"] = (200, "application/javascript", b"export {};")
        data[prefix + "app.css"] = (200, "text/css", b"body { color: black; }")
    return data


@contextmanager
def server(routes):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.command, self.path, dict(self.headers)))
            status, kind, body = routes.get(self.path, (404, "text/plain", b"missing"))
            self.send_response(status)
            self.send_header("Content-Type", kind)
            if status == 302:
                self.send_header("Location", "/must-not-follow")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}", requests
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=2)


def run(routes, expected=COMMIT):
    return doctor.inspect_site(ORIGIN, SHA, expected, lambda url: doctor.Response(*routes[url[len(ORIGIN):]]))


def test_real_http_transport_is_get_only_and_success_is_not_production_approval(routes):
    with server(routes) as (base, requests):
        result = doctor.inspect_site(ORIGIN, SHA, COMMIT,
                                     lambda url: doctor.fetch(base + url[len(ORIGIN):]))
    assert result["status"] == "PUBLIC_READ_ONLY_CANDIDATE_SMOKE_PASSED"
    assert result["production_ready"] is False and result["deployed_by_this_check"] is False
    assert result["unverified_gates"]
    assert len(requests) == 8
    assert {method for method, _, _ in requests} == {"GET"}
    assert all("Cookie" not in h and "Authorization" not in h for _, _, h in requests)
    assert all(not p.startswith(("/local/", "/v1/", "/api/v1/worker")) for _, p, _ in requests)


def test_legacy_html_200_is_explicitly_rejected_without_following_legacy_assets(routes):
    old = b'<title>AmazingWork</title><script type="module" src="/assets/old.js"></script>'
    data = {path: (200, "text/html", old) for path in ["/", "/workshop/", "/workshop/build-meta.json", "/api/v1/me"]}
    result = run(data)
    assert result["status"] == "CHECK_FAILED"
    assert result["failure_kind"] == "LEGACY_SPA_FALLBACK"
    assert len(result["observations"]) == 4
    assert not any(c["passed"] for c in result["checks"])


@pytest.mark.parametrize("field,value", [
    ("mode", "loopback"), ("public_origin", "https://wrong.example"),
    ("web_base", "/"), ("contract_sha256", "0" * 64),
    ("read_only", False), ("read_only", "true"), ("head", "b" * 40),
])
def test_wrong_build_identity_or_unsafe_mode_cannot_pass(routes, field, value):
    status, kind, body = routes["/workshop/build-meta.json"]
    meta = json.loads(body)
    meta[field] = value
    routes["/workshop/build-meta.json"] = status, kind, json.dumps(meta).encode()
    assert run(routes)["status"] == "CHECK_FAILED"


@pytest.mark.parametrize("mime", ["text/html", "application/javascript"])
def test_successful_asset_html_fallback_is_not_a_javascript_file(routes, mime):
    routes["/workshop/assets/app.js"] = 200, mime, b"<html>fallback</html>"
    result = run(routes)
    assert result["status"] == "CHECK_FAILED"
    assert any(c["name"] == "/workshop/assets/app.js" and not c["passed"] for c in result["checks"])


def test_implicit_anonymous_identity_is_rejected(routes):
    routes["/api/v1/me"] = 200, "application/json", b'{"role":"admin"}'
    assert run(routes)["status"] == "CHECK_FAILED"


def test_untrusted_asset_url_is_never_requested(routes):
    routes["/"] = 200, "text/html", b'<script type="module" src="https://other.example/spy.js"></script>'
    assert run(routes)["status"] == "CHECK_FAILED"  # Mapping transport also rejects any unplanned request.


def test_redirect_is_recorded_without_following_it():
    with server({"/": (302, "text/plain", b"redirect")}) as (base, requests):
        response = doctor.fetch(base + "/")
    assert response.status == 302
    assert [path for _, path, _ in requests] == ["/"]


@pytest.mark.parametrize("origin", ["http://magicworkshop.fun", "https://user:secret@example.com",
                                   ORIGIN + "/workshop/", ORIGIN + "?key=value"])
def test_origin_must_be_https_without_credentials_path_or_query(origin):
    with pytest.raises(ValueError):
        doctor.inspect_site(origin, SHA, COMMIT, lambda _: pytest.fail("Network must not be reached"))
