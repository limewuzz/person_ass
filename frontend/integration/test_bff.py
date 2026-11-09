"""Local session boundary tests, independent of GLM source changes."""

import importlib.util, sys
from pathlib import Path
from fastapi.testclient import TestClient as ASGITestClient
import pytest

module_path = Path(__file__).with_name("local_stack.py")
spec = importlib.util.spec_from_file_location("mw_local_bff", module_path)
bff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bff)


def TestClient(app):
    return ASGITestClient(app, base_url=bff.WEB_ORIGIN, client=("127.0.0.1", 50000))


def test_no_cookie_no_admin_proxy():
    with TestClient(bff.app) as c:
        assert c.get("/api/v1/nodes").status_code == 401
        assert (
            c.post(
                "/local/session", headers={"Origin": "https://untrusted.invalid"}
            ).status_code
            == 403
        )


def test_session_is_http_only_and_csrf_protected():
    with TestClient(bff.app) as c:
        r = c.post("/local/session", headers={"Origin": bff.WEB_ORIGIN})
        assert r.status_code == 200
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie
        csrf = r.json()["csrf"]
        assert "token" not in r.json()
        assert (
            c.post(
                "/api/v1/tasks", headers={"Origin": bff.WEB_ORIGIN}, json={}
            ).status_code
            == 403
        )
        assert (
            c.post(
                "/api/v1/tasks",
                headers={"Origin": "https://untrusted.invalid", "X-MW-CSRF": csrf},
                json={},
            ).status_code
            == 403
        )
        assert (
            c.post(
                "/api/v1/workers/forged/claim",
                headers={"Origin": bff.WEB_ORIGIN, "X-MW-CSRF": csrf},
                json={},
            ).status_code
            == 403
        )
        assert (
            c.post(
                "/api/v1/tasks",
                headers={"Origin": bff.WEB_ORIGIN, "X-MW-CSRF": csrf},
                json={},
            ).status_code
            == 400
        )
        assert c.get("/api/v1/resources/svc.tc.cherry-web").status_code == 403


def test_complete_lock_is_required_and_bad_schema_fails():
    errors = bff.validation(
        {"$ref": "#/components/schemas/UIBootstrap"}, {"app_mode": "local-rc"}
    )
    assert len(errors) > 0


def test_proxy_preserves_json_content_type(monkeypatch):
    import httpx, json, uuid

    real = httpx.AsyncClient

    def transport(request):
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content)["title"] == "synthetic"
        return httpx.Response(
            201,
            json={
                "id": str(uuid.uuid4()),
                "title": "synthetic",
                "kind": "task",
                "status": "open",
                "created_at": "2026-11-08T00:00:00Z",
                "created_by": str(uuid.uuid4()),
            },
        )

    monkeypatch.setattr(
        bff.httpx,
        "AsyncClient",
        lambda **kw: real(**kw, transport=httpx.MockTransport(transport)),
    )
    monkeypatch.setitem(bff.tokens, "actor", "synthetic-local-test-token")
    with TestClient(bff.app) as c:
        session = c.post("/local/session", headers={"Origin": bff.WEB_ORIGIN}).json()
        response = c.post(
            "/api/v1/work-items",
            headers={"Origin": bff.WEB_ORIGIN, "X-MW-CSRF": session["csrf"]},
            json={"title": "synthetic", "kind": "task"},
        )
        assert response.status_code == 201


def test_session_refresh_renews_internal_mock_token_without_exposing_it(monkeypatch):
    issued = []

    def issue():
        issued.append(True)
        return "synthetic-renewed-server-only-token"

    monkeypatch.setitem(bff.tokens, "actor_factory", issue)
    with TestClient(bff.app) as c:
        body = c.post("/local/session", headers={"Origin": bff.WEB_ORIGIN}).json()
        assert (
            issued == [True]
            and bff.tokens["actor"] == "synthetic-renewed-server-only-token"
        )
        assert "token" not in body and "synthetic-renewed" not in str(body)


@pytest.mark.parametrize("path", ["me", "ui/bootstrap", "tasks", "nodes", "audit", "events"])
def test_every_private_surface_requires_session(path):
    with TestClient(bff.app) as c:
        response = c.get("/api/v1/" + path)
        assert response.status_code == 401
        assert "items" not in response.json()
        assert response.headers["cache-control"] == "no-store"


def test_public_host_cannot_mint_local_admin_session():
    with TestClient(bff.app) as c:
        response = c.post("/local/session", headers={"Host": "control.example.invalid", "Origin": bff.WEB_ORIGIN})
        assert response.status_code == 403
        assert "set-cookie" not in response.headers


def test_remote_client_cannot_mint_local_session_even_with_forged_origin():
    with ASGITestClient(bff.app, base_url=bff.WEB_ORIGIN, client=("203.0.113.10", 40000)) as c:
        assert c.post("/local/session", headers={"Origin": bff.WEB_ORIGIN}).status_code == 403


def test_expired_session_fails_closed_without_cached_data():
    with TestClient(bff.app) as c:
        c.post("/local/session", headers={"Origin": bff.WEB_ORIGIN})
        sid = c.cookies.get("mw_local_session")
        bff.SESSIONS[sid]["expires"] = bff.time.monotonic() - 1
        assert c.get("/api/v1/me").status_code == 401
        assert c.get("/api/v1/events").status_code == 401
