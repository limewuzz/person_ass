"""Comprehensive test suite for MagicWorkshop V2 all 7 parallel workflows and 95/95 OpenAPI contract operations."""
from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import time
import uuid

import pytest
from fastapi.testclient import TestClient

import app as api
from auth import ROLE_SCOPES, mint_token
from contract_wire import CONTRACT, validator
from approvals import ApprovalService
from taskengine import TaskEngine
from workergw import WorkerGateway
from core.sessions import SessionManager
from ai_hub.service import AIHubService
from agent_os.service import AgentOSService
from worker_hub.service import WorkerHubService
from clients_sync.service import ClientSyncService
from integrations.service import IntegrationsService
from core.router import build_core_v2_router
from ai_hub.router import build_ai_hub_router
from agent_os.router import build_agent_os_router
from worker_hub.router import build_worker_hub_router
from clients_sync.router import build_clients_sync_router
from integrations.router import build_integrations_router
import dbpg.repository as R

SECRET = "test-secret-only-for-local-tests"


def _auth_hdr(sub: str | None = None, role: str = "admin", typ: str = "actor", scopes: list[str] | None = None, jti: str | None = None) -> dict[str, str]:
    actor_sub = sub or str(uuid.uuid4())
    tok = mint_token(
        SECRET,
        sub=actor_sub,
        typ=typ,
        role=role,
        scopes=sorted(ROLE_SCOPES[role]) if scopes is None else scopes,
        jti=jti or str(uuid.uuid4()),
    )
    return {"Authorization": f"Bearer {tok}"}


def _validate_wire(resp, path_template: str, method: str) -> None:
    op = CONTRACT["paths"][path_template][method.lower()]
    status_str = str(resp.status_code)
    assert status_str in op["responses"], (path_template, method, resp.status_code, resp.text)
    schema = (
        op["responses"][status_str]
        .get("content", {})
        .get("application/json", {})
        .get("schema")
    )
    if schema and "$ref" in schema:
        schema_name = schema["$ref"].split("/")[-1]
        errs = list(validator(schema_name).iter_errors(resp.json()))
        assert not errs, (path_template, method, schema_name, [(list(e.path), e.message) for e in errs])


@pytest.fixture()
def client():
    return TestClient(api.app, raise_server_exceptions=False)


# ══════════════════════════════════════════════════════════════════════════
# 1. FULL V2 WIRE CONTRACT COVERAGE (All 52 V2 operations + 43 V1.1.1 = 95)
# ══════════════════════════════════════════════════════════════════════════

def test_all_52_v2_operations_validate_against_frozen_openapi_schema(client):
    admin_sub = str(uuid.uuid4())
    admin = _auth_hdr(sub=admin_sub, role="admin")
    covered_v2: set[tuple[str, str]] = set()

    def call(method: str, path: str, template: str | None = None, json_body=None, headers=None, expected_status: int | None = None):
        t = template or path.split("?")[0]
        h = headers if headers is not None else admin
        r = client.request(method.upper(), path, json=json_body, headers=h)
        if expected_status is not None:
            assert r.status_code == expected_status, (method, path, r.status_code, r.text)
        _validate_wire(r, t, method.lower())
        if CONTRACT["paths"][t][method.lower()].get("x-phase") == "V2":
            covered_v2.add((method.lower(), t))
        return r

    # --- Workflow 1: Platform Core V2 ---
    sess_r = call("post", "/api/v1/auth/session", json_body={"client_platform": "web", "device_id": "dev-web-1"}, expected_status=200)
    csrf = sess_r.json()["csrf_token"]
    assert "mw_session" in sess_r.cookies
    client.cookies.clear()

    # Register -> Patch -> Delete Resource
    res_id = f"svc.v2.test.{uuid.uuid4().hex[:6]}"
    reg_r = call(
        "post",
        "/api/v1/resources",
        json_body={"id": res_id, "kind": "service", "owner_system": "mwcp-v2", "display_name": "V2 Service", "node_id": "us-server"},
        expected_status=201,
    )
    gen1 = reg_r.json()["generation"]
    patch_r = call(
        "patch",
        f"/api/v1/resources/{res_id}",
        "/api/v1/resources/{id}",
        json_body={"expected_generation": gen1, "action": "transfer_owner", "new_owner": "mwcp-v2-next"},
        expected_status=200,
    )
    gen2 = patch_r.json()["generation"]
    assert gen2 > gen1
    call("delete", f"/api/v1/resources/{res_id}?expected_generation={gen2}", "/api/v1/resources/{id}", expected_status=200)

    # WorkItem Dispatch & Reconcile
    wi_id = client.post(
        "/api/v1/work-items",
        json={"title": "V2 Dispatch WorkItem", "kind": "task", "instructions": "Detailed V2 natural language instructions", "attachments": ["att-1"]},
        headers=admin,
    ).json()["id"]
    disp_r = call(
        "post",
        f"/api/v1/work-items/{wi_id}/dispatch",
        "/api/v1/work-items/{id}/dispatch",
        json_body={"capability": "local.simulate", "resource_id": "local-ledger", "arguments": {"outcome": "SUCCEEDED"}, "dry_run": True},
        headers={**admin, "Idempotency-Key": f"idem-disp-{uuid.uuid4().hex[:12]}"},
        expected_status=202,
    )
    dispatched_tid = disp_r.json()["task_id"]
    # Approve -> Claim -> Expire lease -> Reconcile
    aid = next(a.id for a in api._approvals.approvals.values() if a.task_id == dispatched_tid)
    client.post(f"/api/v1/approvals/{aid}/approve", headers=admin)
    worker_hdr = _auth_hdr(sub="w-v2-core", role="worker", typ="worker")
    client.post(
        "/api/v1/workers/w-v2-core/heartbeat",
        json={"node_id": "mac-mini", "version": "2.0", "available_capabilities": ["local.simulate"], "observed_at": "2026-11-10T00:00:00Z"},
        headers=worker_hdr,
    )
    claimed = client.post(
        "/api/v1/workers/w-v2-core/claim",
        json={"limit": 1, "capabilities": ["local.simulate"]},
        headers=worker_hdr,
    ).json()["tasks"][0]
    # Progress report on leased task
    call(
        "post",
        f"/api/v1/workers/w-v2-core/tasks/{dispatched_tid}/progress",
        "/api/v1/workers/{worker_id}/tasks/{task_id}/progress",
        json_body={"generation": claimed["generation"], "lease_token": claimed["lease_token"], "progress_percent": 50, "summary": "Halfway done"},
        headers=worker_hdr,
        expected_status=200,
    )
    # Force transition to NEEDS_RECONCILIATION to test reconcile endpoint
    api._engine.transition(dispatched_tid, "NEEDS_RECONCILIATION", actor="test")
    call(
        "post",
        f"/api/v1/tasks/{dispatched_tid}/reconcile",
        "/api/v1/tasks/{id}/reconcile",
        json_body={"resolution": "SUCCEEDED", "reason": "Verified output manually"},
        expected_status=200,
    )

    # --- Workflow 2: AI Infrastructure V2 ---
    call("get", "/api/v1/ai/providers", expected_status=200)
    prov_id = f"prov.custom.{uuid.uuid4().hex[:6]}"
    call(
        "post",
        "/api/v1/ai/providers",
        json_body={
            "id": prov_id,
            "display_name": "Custom OpenAI Provider",
            "adapter_kind": "openai_compatible",
            "endpoint_url": "https://llm.example.invalid/v1",
            "credential_ref": "vault://custom-llm-key",
            "api_key_secret": "sk-never-return-this-in-response",
            "models": [
                {
                    "id": f"model.custom.{prov_id}",
                    "display_name": "Custom Model 1",
                    "capabilities": {
                        "supports_text": True,
                        "supports_tools": True,
                        "supports_vision": True,
                        "supports_structured_output": True,
                        "context_window": 128000,
                        "rate_limit_rpm": 100,
                        "pricing_tier": "custom",
                    },
                }
            ],
        },
        expected_status=201,
    )
    call(
        "patch",
        f"/api/v1/ai/providers/{prov_id}",
        "/api/v1/ai/providers/{id}",
        json_body={"display_name": "Updated Custom Provider", "enabled": True},
        expected_status=200,
    )
    call("post", f"/api/v1/ai/providers/{prov_id}/probe", "/api/v1/ai/providers/{id}/probe", expected_status=200)
    call("get", f"/api/v1/models/model.custom.{prov_id}", "/api/v1/models/{id}", expected_status=200)
    call("get", "/api/v1/ai/routing-policy", expected_status=200)
    call(
        "put",
        "/api/v1/ai/routing-policy",
        json_body={"default_model_id": "model.deepseek-flash", "fallback_model_id": "model.kimi-k3", "task_routes": {"code": "model.codex-cliproxy"}},
        expected_status=200,
    )
    call(
        "post",
        "/api/v1/ai/completions",
        json_body={"prompt": "Synthesize V2 architecture check", "task_kind": "code", "require_tools": True, "dry_run": True},
        expected_status=200,
    )
    call("delete", f"/api/v1/ai/providers/{prov_id}", "/api/v1/ai/providers/{id}", expected_status=200)

    # --- Workflow 3: Agent OS V2 ---
    ag_id = f"agent.v2.{uuid.uuid4().hex[:6]}"
    call(
        "post",
        "/api/v1/agents",
        json_body={
            "id": ag_id,
            "display_name": "V2 Research Specialist",
            "owner_system": "mwcp-v2",
            "runtime_node_id": "us-server",
            "capabilities": ["local.simulate", "probe.http.get"],
            "default_model_id": "model.deepseek-flash",
            "system_prompt": "Always verify SHA-256 digests.",
        },
        expected_status=201,
    )
    call(
        "patch",
        f"/api/v1/agents/{ag_id}",
        "/api/v1/agents/{id}",
        json_body={"display_name": "V2 Senior Research Specialist"},
        expected_status=200,
    )
    conv_r = call(
        "post",
        "/api/v1/conversations",
        json_body={"title": "V2 Architecture Alignment", "agent_id": ag_id, "work_item_id": wi_id},
        expected_status=201,
    )
    conv_id = conv_r.json()["id"]
    call("get", "/api/v1/conversations", expected_status=200)
    call("get", f"/api/v1/conversations/{conv_id}", "/api/v1/conversations/{id}", expected_status=200)
    msg_r = call(
        "post",
        f"/api/v1/conversations/{conv_id}/messages",
        "/api/v1/conversations/{id}/messages",
        json_body={"content": "Run a simulated verification task", "role": "user", "spawn_capability": "local.simulate"},
        headers={**admin, "Idempotency-Key": f"msg-idem-{uuid.uuid4().hex[:12]}"},
        expected_status=201,
    )
    assert msg_r.json()["spawned_task_id"] is not None and msg_r.json()["approval_id"] is not None
    call("get", f"/api/v1/conversations/{conv_id}/messages", "/api/v1/conversations/{id}/messages", expected_status=200)
    stream_r = client.get(f"/api/v1/conversations/{conv_id}/stream", headers=admin)
    assert stream_r.status_code == 200 and "event: conversation.message" in stream_r.text
    covered_v2.add(("get", "/api/v1/conversations/{id}/stream"))

    call(
        "post",
        "/api/v1/supervisor/plan",
        json_body={"goal": "Coordinate multi-agent release verification", "preferred_agents": [ag_id], "execute_immediately": True, "dry_run": True},
        expected_status=201,
    )
    plug_id = f"plugin.v2.{uuid.uuid4().hex[:6]}"
    call(
        "post",
        "/api/v1/plugins",
        json_body={
            "id": plug_id,
            "name": "V2 Citation Verifier",
            "version": "1.0.0",
            "signature_sha256": "1" * 64,
            "requested_scopes": ["registry:read"],
            "source_repo": "https://github.com/limewuzz/person_ass",
        },
        expected_status=201,
    )
    # Upgrade to v1.1.0 so we can test rollback to v1.0.0
    call(
        "post",
        "/api/v1/plugins",
        json_body={
            "id": plug_id,
            "name": "V2 Citation Verifier",
            "version": "1.1.0",
            "signature_sha256": "2" * 64,
            "requested_scopes": ["registry:read"],
            "source_repo": "https://github.com/limewuzz/person_ass",
        },
        expected_status=201,
    )
    call("get", "/api/v1/plugins", expected_status=200)
    call("post", f"/api/v1/plugins/{plug_id}/enable", "/api/v1/plugins/{id}/enable", expected_status=200)
    call("post", f"/api/v1/plugins/{plug_id}/disable", "/api/v1/plugins/{id}/disable", expected_status=200)
    rb_r = call("post", f"/api/v1/plugins/{plug_id}/rollback", "/api/v1/plugins/{id}/rollback", expected_status=200)
    assert rb_r.json()["version"] == "1.0.0"

    # --- Workflow 4: Compute Resources & Worker Hub V2 ---
    node_id = f"node-v2-{uuid.uuid4().hex[:6]}"
    call(
        "post",
        "/api/v1/nodes/register",
        json_body={
            "id": node_id,
            "name": "V2 Dedicated Compute Node",
            "role": "WORKER",
            "owner_system": "mwcp-v2",
            "cert_fingerprint_sha256": "c" * 64,
        },
        expected_status=201,
    )
    call("post", f"/api/v1/nodes/{node_id}/revoke", "/api/v1/nodes/{id}/revoke", expected_status=200)

    pair_init = call(
        "post",
        "/api/v1/devices/pair/init",
        json_body={"device_name": "MacBook Pro Worker", "platform": "macos", "requested_capabilities": ["local.simulate"]},
        expected_status=201,
    ).json()
    call(
        "post",
        "/api/v1/devices/pair/confirm",
        json_body={"pairing_id": pair_init["pairing_id"], "pairing_code": pair_init["pairing_code"]},
        expected_status=200,
    )

    crun_r = call(
        "post",
        "/api/v1/compute/runs",
        json_body={
            "title": "OVMERD Multimodal Fine-tuning PoC",
            "runtime_kind": "colab_ephemeral",
            "git_commit": "ae654d41712e07d68a4b424f031a694eb27537a7",
            "dataset_sha256": "d" * 64,
            "hyperparameters": {"lr": 1e-4, "epochs": 3},
            "dry_run": True,
        },
        expected_status=201,
    )
    crun_id = crun_r.json()["id"]
    call("get", f"/api/v1/compute/runs/{crun_id}", "/api/v1/compute/runs/{id}", expected_status=200)
    call(
        "post",
        f"/api/v1/compute/runs/{crun_id}/checkpoint",
        "/api/v1/compute/runs/{id}/checkpoint",
        json_body={"step": 100, "artifact_sha256": "e" * 64, "byte_size": 4096, "metrics": {"loss": 0.42}},
        expected_status=200,
    )

    # --- Workflow 5: Multi-Platform Clients V2 ---
    dev_id = f"dev-android-{uuid.uuid4().hex[:6]}"
    call(
        "post",
        "/api/v1/clients/devices",
        json_body={
            "device_id": dev_id,
            "platform": "android",
            "app_version": "2.0.0",
            "os_arch": "Android 15 arm64-v8a",
            "keystore_kind": "android_keystore",
        },
        expected_status=201,
    )
    call("get", "/api/v1/clients/devices", expected_status=200)
    sync_init = call("get", "/api/v1/clients/sync", expected_status=200).json()
    call(
        "post",
        "/api/v1/clients/sync",
        json_body={
            "device_id": dev_id,
            "expected_revision": sync_init["revision"],
            "draft_work_items": [{"title": "Draft from Android"}],
            "ui_preferences": {"theme": "dark", "locale": "zh-CN"},
        },
        expected_status=200,
    )
    call("post", f"/api/v1/clients/devices/{dev_id}/wipe", "/api/v1/clients/devices/{id}/wipe", expected_status=200)
    call("get", "/api/v1/clients/releases/latest", expected_status=200)

    # --- Workflow 6: Data Integrations V2 ---
    raw_bytes = b"# MagicWorkshop V2 Verification Artifact\nAll 7 workflows verified.\n"
    raw_sha = hashlib.sha256(raw_bytes).hexdigest()
    up_ticket = call(
        "post",
        "/api/v1/uploads/tickets",
        json_body={
            "file_name": "v2-verification.md",
            "mime_type": "text/markdown",
            "byte_size": len(raw_bytes),
            "sha256": raw_sha,
        },
        expected_status=201,
    ).json()
    uploaded_art = call(
        "put",
        f"/api/v1/uploads/{up_ticket['ticket_id']}",
        "/api/v1/uploads/{ticket_id}",
        json_body={"content_base64": base64.b64encode(raw_bytes).decode("ascii")},
        expected_status=200,
    ).json()
    dl_ticket = call(
        "post",
        f"/api/v1/artifacts/{uploaded_art['id']}/download-ticket",
        "/api/v1/artifacts/{id}/download-ticket",
        expected_status=200,
    ).json()
    dl_content = call(
        "get",
        f"/api/v1/artifacts/{uploaded_art['id']}/content?ticket={dl_ticket['ticket_id']}",
        "/api/v1/artifacts/{id}/content",
        expected_status=200,
    ).json()
    assert base64.b64decode(dl_content["content_base64"]) == raw_bytes

    call(
        "post",
        "/api/v1/integrations/int.notion/sync",
        "/api/v1/integrations/{id}/sync",
        json_body={"dry_run": True, "summary_note": "Sync V2 parallel architecture decision"},
        expected_status=200,
    )
    call(
        "post",
        "/api/v1/knowledge/query",
        json_body={"query": "全模块同步开发", "sources": ["notion", "drive"], "limit": 5},
        expected_status=200,
    )

    # --- Workflow 7: System Contract Meta & Session Revoke/Logout ---
    meta_r = call("get", "/api/v1/system/contract-meta", expected_status=200).json()
    assert meta_r["total_paths"] == 79 and meta_r["total_operations"] == 95
    assert all(meta_r["workflows_ready"].values())

    call("post", "/api/v1/auth/revoke", json_body={"jti": "jti-to-revoke-v2", "reason": "security drill"}, expected_status=200)
    call("post", "/api/v1/auth/logout", headers={"Cookie": f"mw_session={sess_r.json()['session_id']}", "X-CSRF-Token": csrf, "Origin": "http://testserver"}, expected_status=200)

    expected_v2 = {
        (m.lower(), p)
        for p, ops in CONTRACT["paths"].items()
        for m, spec_op in ops.items()
        if m in {"get", "post", "put", "patch", "delete"} and isinstance(spec_op, dict) and spec_op.get("x-phase") == "V2"
    }
    assert covered_v2 == expected_v2, f"Missing V2 ops: {expected_v2 - covered_v2}"
    assert len(covered_v2) == 52


# ══════════════════════════════════════════════════════════════════════════
# 2. SECURITY, BOUNDARY & NEGATIVE TESTS ACROSS ALL 7 WORKFLOWS
# ══════════════════════════════════════════════════════════════════════════

def test_v2_cookie_session_enforces_csrf_and_blocks_worker_endpoints(client):
    user_hdr = _auth_hdr(sub="cookie-user", role="operator")
    r = client.post("/api/v1/auth/session", json={"client_platform": "web"}, headers=user_hdr)
    assert r.status_code == 200
    client.cookies.clear()
    sid = r.json()["session_id"]
    csrf = r.json()["csrf_token"]
    cookie_hdr = {"Cookie": f"mw_session={sid}"}

    # GET succeeds with HttpOnly cookie
    assert client.get("/api/v1/me", headers=cookie_hdr).status_code == 200

    # Mutating POST without X-CSRF-Token fails closed with 403
    no_csrf = client.post("/api/v1/work-items", json={"title": "CSRF test", "kind": "task"}, headers=cookie_hdr)
    assert no_csrf.status_code == 403 and no_csrf.json()["error"]["code"] == "csrf_validation_failed"

    # Mutating POST with valid X-CSRF-Token succeeds
    with_csrf = client.post(
        "/api/v1/work-items",
        json={"title": "CSRF test ok", "kind": "task"},
        headers={**cookie_hdr, "X-CSRF-Token": csrf, "Origin": "http://testserver"},
    )
    assert with_csrf.status_code == 201

    # Browser session cookie is strictly forbidden from calling Worker endpoints
    w_res = client.post(
        "/api/v1/workers/cookie-user/claim",
        json={"limit": 1},
        headers={**cookie_hdr, "X-CSRF-Token": csrf, "Origin": "http://testserver"},
    )
    assert w_res.status_code == 403 and w_res.json()["error"]["code"] == "worker_cookie_forbidden"


def test_v2_ai_hub_secret_isolation_and_cherry_freeze(client):
    admin = _auth_hdr(role="admin")
    # Attempting to register a Cherry Studio endpoint is blocked
    cherry_r = client.post(
        "/api/v1/ai/providers",
        json={
            "id": "prov.cherry",
            "display_name": "Cherry",
            "adapter_kind": "openai_compatible",
            "endpoint_url": "https://cherry.example.com/v1",
            "credential_ref": "vault://c",
            "models": [],
        },
        headers=admin,
    )
    assert cherry_r.status_code == 403

    # Register valid provider with api_key_secret and ensure secret never leaks in GET/POST
    secret_str = "sk-live-super-secret-value-99999"
    p_id = f"prov.sec.{uuid.uuid4().hex[:6]}"
    create_r = client.post(
        "/api/v1/ai/providers",
        json={
            "id": p_id,
            "display_name": "Secret Isolation Provider",
            "adapter_kind": "gemini_native",
            "endpoint_url": "https://generativelanguage.googleapis.com/v1beta",
            "credential_ref": "vault://gemini-sec",
            "api_key_secret": secret_str,
            "models": [
                {
                    "id": f"m.{p_id}",
                    "display_name": "Gemini Text Only",
                    "capabilities": {
                        "supports_text": True,
                        "supports_tools": False,
                        "supports_vision": False,
                        "supports_structured_output": True,
                        "context_window": 32000,
                        "rate_limit_rpm": 30,
                        "pricing_tier": "standard",
                    },
                }
            ],
        },
        headers=admin,
    )
    assert create_r.status_code == 201
    assert secret_str not in create_r.text
    assert create_r.json()["has_secret_configured"] is True

    list_r = client.get("/api/v1/ai/providers", headers=admin)
    assert secret_str not in list_r.text

    # Requesting vision or tools on a text-only model is rejected with 400
    comp_r = client.post(
        "/api/v1/ai/completions",
        json={"model_id": f"m.{p_id}", "prompt": "Analyze image", "require_vision": True, "dry_run": True},
        headers=admin,
    )
    assert comp_r.status_code == 400 and "vision" in comp_r.json()["error"]["code"]


def test_v2_agent_os_conversation_idor_idempotency_and_plugin_privilege_guard(client):
    alice = _auth_hdr(sub="alice-v2", role="operator")
    bob = _auth_hdr(sub="bob-v2", role="operator")
    admin = _auth_hdr(role="admin")

    conv = client.post("/api/v1/conversations", json={"title": "Alice Private Thread"}, headers=alice).json()
    cid = conv["id"]

    # Bob cannot read or append to Alice's conversation (IDOR check)
    assert client.get(f"/api/v1/conversations/{cid}", headers=bob).status_code == 403
    assert client.get(f"/api/v1/conversations/{cid}/messages", headers=bob).status_code == 403
    assert client.get(f"/api/v1/conversations/{cid}/stream", headers=bob).status_code == 403

    # Alice idempotent message append: same key + same body -> replayed=True; different body -> 409
    idem_hdr = {**alice, "Idempotency-Key": "msg-key-000000001"}
    m1 = client.post(f"/api/v1/conversations/{cid}/messages", json={"content": "Hello V2"}, headers=idem_hdr)
    m2 = client.post(f"/api/v1/conversations/{cid}/messages", json={"content": "Hello V2"}, headers=idem_hdr)
    assert m1.status_code == 201 and m2.status_code == 201
    assert m1.json()["id"] == m2.json()["id"]
    assert m1.json()["replayed"] is False and m2.json()["replayed"] is True

    conflict = client.post(f"/api/v1/conversations/{cid}/messages", json={"content": "Tampered"}, headers=idem_hdr)
    assert conflict.status_code == 409

    # Plugin privilege escalation check (V2-EXT-006): requesting admin:* or worker:* is rejected with 403
    for bad_scope in ["admin:write", "worker:claim", "shell:exec"]:
        pr = client.post(
            "/api/v1/plugins",
            json={
                "id": "plugin.evil",
                "name": "Evil Plugin",
                "version": "1.0.0",
                "signature_sha256": "f" * 64,
                "requested_scopes": [bad_scope],
                "source_repo": "https://github.com/example/plugin",
            },
            headers=admin,
        )
        assert pr.status_code == 403


def test_v2_client_sync_optimistic_concurrency_and_remote_wipe(client):
    user = _auth_hdr(sub="sync-user-1", role="operator")
    # Mismatched keystore for macOS is rejected with 400
    bad_dev = client.post(
        "/api/v1/clients/devices",
        json={
            "device_id": "mac-1",
            "platform": "macos",
            "app_version": "2.0.0",
            "os_arch": "macOS 15 arm64",
            "keystore_kind": "android_keystore",
        },
        headers=user,
    )
    assert bad_dev.status_code == 400

    # Valid registration
    ok_dev = client.post(
        "/api/v1/clients/devices",
        json={
            "device_id": "mac-1",
            "platform": "macos",
            "app_version": "2.0.0",
            "os_arch": "macOS 15 arm64",
            "keystore_kind": "macos_keychain",
        },
        headers=user,
    )
    assert ok_dev.status_code == 201

    # Sync revision 0 -> 1 succeeds; stale revision 0 -> 409 sync_conflict
    s1 = client.post(
        "/api/v1/clients/sync",
        json={"device_id": "mac-1", "expected_revision": 0, "draft_work_items": [], "ui_preferences": {"theme": "dark"}},
        headers=user,
    )
    assert s1.status_code == 200 and s1.json()["revision"] == 1

    stale = client.post(
        "/api/v1/clients/sync",
        json={"device_id": "mac-1", "expected_revision": 0, "draft_work_items": [], "ui_preferences": {"theme": "light"}},
        headers=user,
    )
    assert stale.status_code == 409

    # Remote wipe blocks subsequent sync from wiped device
    client.post("/api/v1/clients/devices/mac-1/wipe", headers=user)
    wiped_sync = client.post(
        "/api/v1/clients/sync",
        json={"device_id": "mac-1", "expected_revision": 1, "draft_work_items": [], "ui_preferences": {}},
        headers=user,
    )
    assert wiped_sync.status_code == 403


def test_v2_uploads_checksum_and_external_uri_proxy_rejection(client):
    user = _auth_hdr(sub="upload-user-1", role="operator")
    # Path traversal filename is rejected
    bad_fn = client.post(
        "/api/v1/uploads/tickets",
        json={"file_name": "../etc/passwd", "mime_type": "text/plain", "byte_size": 10, "sha256": "a" * 64},
        headers=user,
    )
    assert bad_fn.status_code == 400

    # SHA-256 mismatch on upload completion is rejected with 400
    data = b"correct content"
    wrong_sha = "0" * 64
    tk = client.post(
        "/api/v1/uploads/tickets",
        json={"file_name": "notes.txt", "mime_type": "text/plain", "byte_size": len(data), "sha256": wrong_sha},
        headers=user,
    ).json()
    put_bad = client.put(
        f"/api/v1/uploads/{tk['ticket_id']}",
        json={"content_base64": base64.b64encode(data).decode("ascii")},
        headers=user,
    )
    assert put_bad.status_code == 400 and put_bad.json()["error"]["code"] == "sha256_mismatch"

    # External URI proxy attempt on artifact download is blocked with 403
    ext_art_id = str(uuid.uuid4())
    api._engine.artifacts[ext_art_id] = {
        "id": ext_art_id,
        "task_id": "none",
        "storage_system": "EXTERNAL",
        "uri": "https://internal.example.invalid/secret",
        "sha256": "a" * 64,
        "byte_size": 12,
    }
    proxy_attempt = client.get(f"/api/v1/artifacts/{ext_art_id}/content", headers=_auth_hdr(role="admin"))
    assert proxy_attempt.status_code == 403


def test_v2_dbpg_repositories_and_0004_migration_offline():
    mig_0004 = (pathlib.Path(__file__).resolve().parents[2] / "dbpg" / "migrations" / "0004_v2_modules.sql").read_text()
    for table in ("ai_providers", "conversations", "conversation_messages", "plugins", "compute_runs", "client_devices", "client_sync_states", "upload_tickets"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in mig_0004

    calls = []

    class _DummyCursor:
        rowcount = 1
        description = [("id",)]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=()):
            calls.append((" ".join(sql.split()).lower(), params))

        def fetchone(self):
            return ("id-1", "hash-1")

        def fetchall(self):
            return [("id-1",)]

    class _DummyConn:
        def cursor(self):
            return _DummyCursor()

    repos = R.PgRepositories(_DummyConn())
    repos.ai_hub.upsert_provider(
        provider_id="p1",
        display_name="P1",
        adapter_kind="openai_compatible",
        endpoint_url="https://x",
        credential_ref="vault://1",
        status="UNKNOWN",
        enabled=False,
        models_json="[]",
    )
    repos.agent_os.insert_conversation(conv_id=str(uuid.uuid4()), title="T", owner_sub="u1", agent_id=None, work_item_id=None)
    repos.worker_hub.insert_compute_run(run_id="r1", title="R", runtime_kind="local_worker", git_commit="abcdef1", dataset_sha256="a" * 64, execution_id="ex1")
    repos.client_sync.upsert_device(device_id="d1", owner_sub="u1", platform="android", app_version="2.0", os_arch="arm64", keystore_kind="android_keystore")
    assert repos.client_sync.cas_update_sync_state(owner_sub="u1", expected_revision=0, new_cursor="c1", drafts_json="[]", prefs_json="{}") is True
    repos.integrations.insert_upload_ticket(
        ticket_id=str(uuid.uuid4()),
        owner_sub="u1",
        file_name="a.txt",
        mime_type="text/plain",
        byte_size=10,
        expected_sha256="b" * 64,
        task_id=None,
        expires_at=time.time() + 600,
    )
    assert len(calls) == 7
    assert any("insert into client_sync_states" in sql for sql, _ in calls)
