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


# ══════════ V2 Workspace End-to-End BFF Loopback Tests (Conversations, AI Routing, Uploads/Downloads, Sync) ══════════

def _wire_bff_to_real_v2_backend(monkeypatch):
    import base64, hashlib, httpx, os, uuid
    secret_val = "test-secret-only-for-local-tests"
    os.environ["MWCP_AUTH_SECRETS"] = "dev-1:" + secret_val
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    import app as raw_backend
    from auth import mint_token, ROLE_SCOPES, TokenValidator
    if raw_backend._validator is None:
        raw_backend._validator = TokenValidator({"dev-1": secret_val})
        raw_backend._validator_holder["validator"] = raw_backend._validator
    actor_tok = mint_token(
        secret_val,
        sub="bff-v2-workspace-user",
        typ="actor",
        role="admin",
        scopes=sorted(ROLE_SCOPES["admin"]),
        jti=str(uuid.uuid4()),
    )
    monkeypatch.setitem(bff.tokens, "actor", actor_tok)
    monkeypatch.setitem(bff.tokens, "actor_factory", lambda: actor_tok)

    # Bridge httpx.AsyncClient inside BFF directly to raw_backend.app via TestClient
    backend_client = ASGITestClient(raw_backend.app, raise_server_exceptions=False)
    real_async_client = httpx.AsyncClient

    def _bridge_transport(request: httpx.Request) -> httpx.Response:
        resp = backend_client.request(
            request.method,
            request.url.raw_path.decode("ascii"),
            headers=dict(request.headers),
            content=request.content,
        )
        return httpx.Response(
            resp.status_code,
            headers=dict(resp.headers),
            content=resp.content,
            request=request,
        )

    monkeypatch.setattr(
        bff.httpx,
        "AsyncClient",
        lambda **kw: real_async_client(
            **{k: v for k, v in kw.items() if k != "transport"},
            transport=httpx.MockTransport(_bridge_transport),
        ),
    )


def test_v2_bff_workspace_conversations_and_sse_stream(monkeypatch):
    _wire_bff_to_real_v2_backend(monkeypatch)
    with TestClient(bff.app) as c:
        sess = c.post("/local/session", headers={"Origin": bff.WEB_ORIGIN}).json()
        hdrs = {"Origin": bff.WEB_ORIGIN, "X-MW-CSRF": sess["csrf"]}

        # Create conversation via BFF
        conv_r = c.post(
            "/api/v1/conversations",
            headers=hdrs,
            json={"title": "V2 BFF Workspace Conversation", "agent_id": "agent.rakazo.chief"},
        )
        assert conv_r.status_code == 201, conv_r.text
        cid = conv_r.json()["id"]

        # Append message idempotently and spawn governed task
        msg_hdrs = {**hdrs, "Idempotency-Key": "bff-conv-msg-00001"}
        msg_r = c.post(
            f"/api/v1/conversations/{cid}/messages",
            headers=msg_hdrs,
            json={"content": "请协助发起模拟任务", "role": "user", "spawn_capability": "local.simulate"},
        )
        assert msg_r.status_code == 201, msg_r.text
        assert msg_r.json()["spawned_task_id"] is not None

        # Replay returns replayed=True
        replay_r = c.post(
            f"/api/v1/conversations/{cid}/messages",
            headers=msg_hdrs,
            json={"content": "请协助发起模拟任务", "role": "user", "spawn_capability": "local.simulate"},
        )
        assert replay_r.status_code == 201 and replay_r.json()["replayed"] is True

        # Stream conversation SSE through BFF
        stream_r = c.get(f"/api/v1/conversations/{cid}/stream")
        assert stream_r.status_code == 200
        assert "event: conversation.message" in stream_r.text


def test_v2_bff_workspace_ai_routing_and_completions(monkeypatch):
    _wire_bff_to_real_v2_backend(monkeypatch)
    with TestClient(bff.app) as c:
        sess = c.post("/local/session", headers={"Origin": bff.WEB_ORIGIN}).json()
        hdrs = {"Origin": bff.WEB_ORIGIN, "X-MW-CSRF": sess["csrf"]}

        provs = c.get("/api/v1/ai/providers")
        assert provs.status_code == 200 and len(provs.json()["items"]) >= 4

        pol = c.put(
            "/api/v1/ai/routing-policy",
            headers=hdrs,
            json={
                "default_model_id": "model.deepseek-flash",
                "fallback_model_id": "model.kimi-k3",
                "task_routes": {"code": "model.codex-cliproxy"},
            },
        )
        assert pol.status_code == 200
        assert pol.json()["task_routes"]["code"] == "model.codex-cliproxy"

        comp = c.post(
            "/api/v1/ai/completions",
            headers=hdrs,
            json={"prompt": "Verify BFF AI routing", "task_kind": "code", "dry_run": True},
        )
        assert comp.status_code == 200
        assert comp.json()["routed_model_id"] == "model.codex-cliproxy"


def test_v2_bff_workspace_verified_upload_and_download(monkeypatch):
    import base64, hashlib
    _wire_bff_to_real_v2_backend(monkeypatch)
    with TestClient(bff.app) as c:
        sess = c.post("/local/session", headers={"Origin": bff.WEB_ORIGIN}).json()
        hdrs = {"Origin": bff.WEB_ORIGIN, "X-MW-CSRF": sess["csrf"]}

        raw = b"# BFF Uploaded Markdown Note\nVerified end-to-end.\n"
        sha = hashlib.sha256(raw).hexdigest()
        tk_r = c.post(
            "/api/v1/uploads/tickets",
            headers=hdrs,
            json={"file_name": "bff-note.md", "mime_type": "text/markdown", "byte_size": len(raw), "sha256": sha},
        )
        assert tk_r.status_code == 201
        tid = tk_r.json()["ticket_id"]

        art_r = c.put(
            f"/api/v1/uploads/{tid}",
            headers=hdrs,
            json={"content_base64": base64.b64encode(raw).decode("ascii")},
        )
        assert art_r.status_code == 200
        art_id = art_r.json()["id"]

        dl_tk_r = c.post(f"/api/v1/artifacts/{art_id}/download-ticket", headers=hdrs)
        assert dl_tk_r.status_code == 200
        dl_tk = dl_tk_r.json()["ticket_id"]

        dl_r = c.get(f"/api/v1/artifacts/{art_id}/content?ticket={dl_tk}")
        assert dl_r.status_code == 200
        env = dl_r.json()
        assert env["sha256"] == sha
        assert base64.b64decode(env["content_base64"]) == raw


def test_v2_bff_workspace_multi_device_sync_and_conflict(monkeypatch):
    _wire_bff_to_real_v2_backend(monkeypatch)
    with TestClient(bff.app) as c:
        sess = c.post("/local/session", headers={"Origin": bff.WEB_ORIGIN}).json()
        hdrs = {"Origin": bff.WEB_ORIGIN, "X-MW-CSRF": sess["csrf"]}

        dev_r = c.post(
            "/api/v1/clients/devices",
            headers=hdrs,
            json={
                "device_id": "web-workspace-primary",
                "platform": "web",
                "app_version": "2.0.0-rc1",
                "os_arch": "browser-wasm",
                "keystore_kind": "web_httponly_cookie",
            },
        )
        assert dev_r.status_code == 201

        cur = c.get("/api/v1/clients/sync").json()
        rev = cur["revision"]
        sync_ok = c.post(
            "/api/v1/clients/sync",
            headers=hdrs,
            json={
                "device_id": "web-workspace-primary",
                "expected_revision": rev,
                "draft_work_items": [{"title": "Cross-device draft", "kind": "task"}],
                "ui_preferences": {"theme": "dark", "locale": "zh-CN"},
            },
        )
        assert sync_ok.status_code == 200 and sync_ok.json()["revision"] == rev + 1

        # Stale revision triggers 409 conflict through BFF
        sync_conflict = c.post(
            "/api/v1/clients/sync",
            headers=hdrs,
            json={
                "device_id": "web-workspace-primary",
                "expected_revision": rev,
                "draft_work_items": [],
                "ui_preferences": {},
            },
        )
        assert sync_conflict.status_code == 409
