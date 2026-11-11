"""V3 real API and domain tests. All providers and database runtime stay offline."""

import copy
import hashlib
import hmac
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import app as api
from auth import Principal, ROLE_SCOPES, mint_token
from durable_state import DomainCheckpoint
from contract_wire import CONTRACT
from taskengine import TaskEngineError


@pytest.fixture
def env(monkeypatch):
    codec = DomainCheckpoint(api)
    before = codec.dump()
    fan = api._fanout
    dirty = set(fan._dirty)
    for name in ("plans", "deliveries", "idempotency", "nonces"):
        setattr(fan, name, {})
    fan._dirty.clear()
    monkeypatch.delenv("MWCP_FANOUT_GRANTS_FILE", raising=False)
    monkeypatch.delenv("MWCP_WEBHOOK_KEYS_FILE", raising=False)
    client = TestClient(
        api.app, base_url="https://testserver", raise_server_exceptions=False
    )
    principal = Principal(str(uuid.uuid4()), "actor", "admin", ROLE_SCOPES["admin"])
    token = mint_token(
        "test-secret-only-for-local-tests",
        sub=principal.sub,
        typ="actor",
        role="admin",
        scopes=sorted(principal.scopes),
    )
    headers = {
        "Authorization": "Bearer " + token,
        "Idempotency-Key": "v3-intent-0123456789",
    }
    yield client, headers, fan, principal, codec
    codec.load(before)
    fan._dirty = dirty


def intent(recipe="paper", targets=None, mode="SIMULATE"):
    return {
        "recipe_id": recipe,
        "title": "V3 local intent",
        "input": "Review this local paper summary",
        "mode": mode,
        "targets": targets or ["archive", "paper", "reminder", "experiment"],
        "origin": {"channel": "web"},
    }


def create(env, body=None):
    client, headers, _, _, _ = env
    r = client.post("/api/v1/fanouts", json=body or intent(), headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def simulate(env, pid, body=None):
    r = env[0].post(f"/api/v1/fanouts/{pid}/simulate", json=body or {}, headers=env[1])
    assert r.status_code == 200, r.text
    return r.json()


def result(item, outcome="SUCCEEDED"):
    return {
        "claim_token": item["claim_token"],
        "generation": item["generation"],
        "outcome": outcome,
        "receipt": {
            "sha256": "a" * 64,
            "uri": "mock://receipt/" + item["id"],
            "source_mode": "MOCK",
        },
    }


def test_single_work_item_shared_trace_aggregate_gate_and_dependency_convergence(env):
    c, h, s, p, _ = env
    before = len(s.engine.work_items)
    plan = create(env)
    assert len(s.engine.work_items) == before + 1
    assert len({s.engine.tasks[d["task_id"]].trace_id for d in plan["deliveries"]}) == 1
    assert all(
        s.engine.tasks[d["task_id"]].work_item_id == plan["work_item_id"]
        for d in plan["deliveries"]
    )
    assert (
        len([a for a in s.approvals.approvals.values() if a.task_id == plan["task_id"]])
        == 1
    )
    low = simulate(env, plan["id"])
    assert (
        next(d for d in low["deliveries"] if d["step_id"] == "experiment")["attempts"]
        == 0
    )
    decision = c.post(
        f"/api/v1/fanouts/{plan['id']}/decision",
        json={"decision": "approved"},
        headers=h,
    )
    assert decision.status_code == 200, decision.text
    for _ in range(4):
        final = simulate(env, plan["id"])
    assert final["status"] == "SUCCEEDED"
    assert all(
        d["attempts"] == 1 and d["receipt"]["source_mode"] == "MOCK"
        for d in final["deliveries"]
    )
    assert s.engine.tasks[plan["task_id"]].state == "SUCCEEDED"
    assert s.engine.work_items[plan["work_item_id"]].status == "done"
    assert "claim_hash" not in json.dumps(final)


def test_concurrent_idempotency_creates_exactly_one_plan_and_conflict(env):
    _, _, s, p, _ = env
    before = len(s.engine.work_items)
    with ThreadPoolExecutor(max_workers=16) as pool:
        out = list(
            pool.map(lambda _: s.create(intent(), p, "concurrent-intent"), range(100))
        )
    assert len({x[0]["id"] for x in out}) == 1 and sum(not x[1] for x in out) == 1
    assert len(s.engine.work_items) == before + 1
    with pytest.raises(TaskEngineError, match="idempotency_conflict"):
        s.create({**intent(), "title": "different"}, p, "concurrent-intent")


@pytest.mark.parametrize("resolution", ["rejected", "expired"])
def test_gate_closure_preserves_low_siblings(env, resolution):
    c, h, s, p, _ = env
    plan = create(env)
    simulate(env, plan["id"])
    if resolution == "rejected":
        s.decide(plan["id"], p, "rejected")
    else:
        s.approvals.approvals[plan["approval_id"]].expires_at = 1.0
        s.refresh()
    for _ in range(3):
        final = simulate(env, plan["id"])
    assert next(d for d in final["deliveries"] if d["step_id"] == "experiment")[
        "state"
    ] in {"EXPIRED", "CANCELED"}
    assert all(
        d["state"] == "SUCCEEDED" for d in final["deliveries"] if d["risk"] == "LOW"
    )


def test_retry_failed_branch_only_and_lease_unknown_requires_reconciliation(
    env, monkeypatch
):
    _, _, s, p, _ = env
    now = [time.time()]
    monkeypatch.setattr(s, "clock", lambda: now[0])
    plan = create(env, intent("wechat", ["context", "reminder", "confirmation"]))
    claimed = s.claim(
        "relay", ["fanout.knowledge", "fanout.reminders", "fanout.wechat"], 10
    )
    a, b, c = claimed
    s.finish(a["id"], "relay", result(a))
    s.finish(b["id"], "relay", result(b, "RETRYABLE"))
    assert not s.claim("relay", ["fanout.reminders"])
    now[0] += 3
    retry = s.claim("relay", ["fanout.reminders"])[0]
    assert retry["id"] == b["id"] and retry["generation"] == 2
    s.finish(retry["id"], "relay", result(retry))
    now[0] += 61
    s.refresh()
    with pytest.raises(TaskEngineError, match="late_result"):
        s.finish(c["id"], "relay", result(c))
    assert not s.claim("other", ["fanout.wechat"])
    s.reconcile(
        plan["id"],
        c["id"],
        p,
        {
            "expected_generation": 1,
            "resolution": "RETRY_CONFIRMED_NOT_EXECUTED",
            "reason": "Confirmed no external write occurred",
        },
    )
    new = s.claim("relay", ["fanout.wechat"])[0]
    assert new["generation"] == 2
    done = s.finish(new["id"], "relay", result(new))
    assert done["state"] == "SUCCEEDED"
    assert s.finish(new["id"], "relay", result(new))["replayed"]
    assert all(d["state"] == "SUCCEEDED" for d in s.view(plan["id"], p)["deliveries"])
    assert s.deliveries[a["id"]]["attempts"] == 1


def test_unknown_accept_receipt_cas_and_terminal_dependency_cancel(env):
    _, _, s, p, _ = env
    plan = create(env, intent("decision", ["implementation"]))
    first = s.claim("relay", ["fanout.notion"])[0]
    s.finish(first["id"], "relay", result(first, "UNKNOWN"))
    body = {
        "expected_generation": 1,
        "resolution": "FAIL",
        "reason": "Provider confirmed definitive failure",
    }
    final = s.reconcile(plan["id"], first["id"], p, body)
    # Rejecting the approval then cancels the gated descendants, preserving a closed DAG.
    s.decide(plan["id"], p, "rejected")
    assert all(
        d["state"] in {"FAILED", "CANCELED"}
        for d in s.view(plan["id"], p)["deliveries"]
    )
    with pytest.raises(TaskEngineError, match="reconciliation_conflict"):
        s.reconcile(plan["id"], first["id"], p, body)


def test_ownership_scopes_live_fail_closed_and_old_worker_cannot_steal(env):
    c, h, s, p, _ = env
    plan = create(env, intent("wechat", ["reminder"], mode="LIVE"))
    assert plan["availability"] == "UNAVAILABLE"
    assert not s.claim("relay", ["fanout.reminders"], mode="LIVE")
    assert (
        c.post(f"/api/v1/fanouts/{plan['id']}/simulate", json={}, headers=h).status_code
        == 403
    )
    outsider = Principal("outsider", "actor", "operator", ROLE_SCOPES["operator"])
    with pytest.raises(TaskEngineError, match="fanout_forbidden"):
        s.view(plan["id"], outsider)
    for path in [
        "/api/v1/workers/relay/outbox/claim",
        "/api/v1/workers/relay/outbox/delivery/finish",
    ]:
        assert c.post(path, json={"mode": "SIMULATE"}, headers=h).status_code == 403
    api._gateway.heartbeat(
        "relay",
        node_id="test",
        version="3",
        available_capabilities=["fanout.reminders"],
    )
    assert not api._gateway.claim("relay", limit=10)


def test_worker_auth_claim_finish_and_response_schema(env):
    c, h, s, p, _ = env
    plan = create(env, intent("wechat", ["reminder"]))
    token = mint_token(
        "test-secret-only-for-local-tests",
        sub="v3-relay",
        typ="worker",
        role="worker",
        scopes=["worker:heartbeat", "worker:claim"],
    )
    wh = {"Authorization": "Bearer " + token}
    hb = c.post(
        "/api/v1/workers/v3-relay/heartbeat",
        json={
            "node_id": "local-test-node",
            "version": "3",
            "observed_at": "2026-11-10T00:00:00Z",
            "available_capabilities": ["fanout.reminders"],
        },
        headers=wh,
    )
    assert hb.status_code == 200, hb.text
    claim = c.post(
        "/api/v1/workers/v3-relay/outbox/claim", json={"mode": "SIMULATE"}, headers=wh
    )
    assert claim.status_code == 200, claim.text
    item = claim.json()["items"][0]
    out = c.post(
        "/api/v1/workers/v3-relay/outbox/" + item["id"] + "/finish",
        json=result(item),
        headers=wh,
    )
    assert out.status_code == 200, out.text
    assert (
        c.post(
            "/api/v1/workers/other/outbox/claim", json={"mode": "SIMULATE"}, headers=wh
        ).status_code
        == 403
    )
    assert (
        c.get("/api/v1/fanouts/" + plan["id"], headers=h).json()["status"]
        == "SUCCEEDED"
    )


def webhook_config(
    tmp_path, monkeypatch, owner, recipes=None, channel="wechat", **extras
):
    secret = tmp_path / "key"
    secret.write_bytes(b"v3-test-only-not-production-secret-123456")
    secret.chmod(0o600)
    config = tmp_path / "keys.json"
    config.write_text(
        json.dumps(
            {
                "keys": {
                    "test": {
                        "secret_file": str(secret),
                        "owner_sub": owner,
                        "channel": channel,
                        "recipes": recipes or ["wechat"],
                        **extras,
                    }
                }
            }
        )
    )
    monkeypatch.setenv("MWCP_WEBHOOK_KEYS_FILE", str(config))
    return secret


def signed(raw, secret, key="signed-intent-123456", nonce="nonce-1234567890", ts=None):
    ts = str(int(time.time()) if ts is None else ts)
    value = f"{ts}\n{nonce}\n{key}\n{hashlib.sha256(raw).hexdigest()}".encode()
    return {
        "X-MW-Key-Id": "test",
        "X-MW-Timestamp": ts,
        "X-MW-Nonce": nonce,
        "Idempotency-Key": key,
        "X-MW-Signature": hmac.new(
            secret.read_bytes(), value, hashlib.sha256
        ).hexdigest(),
        "Content-Type": "application/json",
    }


def test_hmac_scope_replay_timestamp_body_size_and_idempotent_response(
    env, tmp_path, monkeypatch
):
    c, _, s, p, _ = env
    body = intent("wechat", ["reminder"])
    body["origin"]["channel"] = "wechat"
    raw = json.dumps(body).encode()
    assert c.post("/api/v1/webhooks/trigger", content=raw).status_code == 503
    secret = webhook_config(tmp_path, monkeypatch, p.sub)
    headers = signed(raw, secret)
    first = c.post("/api/v1/webhooks/trigger", content=raw, headers=headers)
    assert first.status_code == 201, first.text
    assert (
        c.post("/api/v1/webhooks/trigger", content=raw, headers=headers).json()["id"]
        == first.json()["id"]
    )
    altered = {**headers, "Idempotency-Key": "changed-header-key-123"}
    assert (
        c.post("/api/v1/webhooks/trigger", content=raw, headers=altered).status_code
        == 401
    )
    body["title"] = "altered"
    other = json.dumps(body).encode()
    assert (
        c.post(
            "/api/v1/webhooks/trigger", content=other, headers=signed(other, secret)
        ).status_code
        == 409
    )
    assert (
        c.post(
            "/api/v1/webhooks/trigger", content=raw, headers=signed(raw, secret, ts=1)
        ).status_code
        == 401
    )
    body["origin"]["channel"] = "web"
    other = json.dumps(body).encode()
    assert (
        c.post(
            "/api/v1/webhooks/trigger",
            content=other,
            headers=signed(other, secret, nonce="different-nonce-123"),
        ).status_code
        == 403
    )
    assert (
        c.post(
            "/api/v1/webhooks/trigger", content=b"x" * 65537, headers=headers
        ).status_code
        == 400
    )
    secret.chmod(0o644)
    assert (
        c.post("/api/v1/webhooks/trigger", content=raw, headers=headers).status_code
        == 401
    )


def test_existing_work_item_and_conversation_entries_delegate_without_duplicate(env):
    c, h, s, p, _ = env
    wi = c.post(
        "/api/v1/work-items", json={"title": "shared item", "kind": "task"}, headers=h
    ).json()["id"]
    out = c.post(f"/api/v1/work-items/{wi}/dispatch", json=intent(), headers=h)
    assert out.status_code == 202, out.text
    assert out.json()["work_item_id"] == wi
    conv = c.post(
        "/api/v1/conversations", json={"title": "paper discussion"}, headers=h
    ).json()["id"]
    body = {"content": "Manual pasted decision", "fanout": intent("decision", ["adr"])}
    first = c.post(f"/api/v1/conversations/{conv}/messages", json=body, headers=h)
    assert first.status_code == 201, first.text
    second = c.post(f"/api/v1/conversations/{conv}/messages", json=body, headers=h)
    assert second.status_code == 201, second.text
    assert first.json()["fanout"]["id"] == second.json()["fanout"]["id"]
    assert (
        len(c.get(f"/api/v1/conversations/{conv}/messages", headers=h).json()["items"])
        == 1
    )


def test_codec_one_upgrade_no_credentials_codec_two_strict_and_frozen_v2_contract(env):
    _, _, s, p, codec = env
    create(env)
    doc = json.loads(codec.dump())
    assert doc["codec_version"] == 2
    assert "claim_token" not in json.dumps(doc) and "secret_file" not in json.dumps(doc)
    codec.load(doc)
    legacy = copy.deepcopy(doc)
    legacy["codec_version"] = 1
    del legacy["values"]["_fanout"]
    codec.load(legacy)
    assert not s.plans
    bad = copy.deepcopy(legacy)
    bad["codec_version"] = 2
    with pytest.raises(ValueError):
        codec.load(bad)
    old = Path(__file__).parents[2] / "contracts/snapshots/v2.0.1/openapi.yaml"
    assert (
        hashlib.sha256(old.read_bytes()).hexdigest()
        == "d94462c44cd7c331470fc79731da29a7539d78f770b52288fce590ae3f52504f"
    )


def test_checkpoint_live_requires_run_scoped_key_not_browser_and_no_fake_bytes(
    env, tmp_path, monkeypatch
):
    c, h, s, p, _ = env
    from worker_hub.service import ComputeRunRec

    rid = str(uuid.uuid4())
    api._worker_hub.compute_runs[rid] = ComputeRunRec(
        rid,
        "offline test",
        "colab",
        "a" * 40,
        "b" * 64,
        "execution",
        "RUNNING",
        source_kind="live",
    )
    body = intent("checkpoint", ["checkpoint", "metrics"], mode="LIVE")
    body["origin"]["channel"] = "colab"
    body["parameters"] = {
        "run_id": rid,
        "step": 10,
        "byte_size": 2048,
        "checkpoint_uri": "https://drive.google.com/file/d/test-reference/view",
        "checkpoint_sha256": "c" * 64,
        "metrics": {"loss": 0.3},
    }
    assert c.post("/api/v1/fanouts", json=body, headers=h).status_code == 403
    secret = webhook_config(
        tmp_path,
        monkeypatch,
        p.sub,
        ["checkpoint"],
        "colab",
        run_ids=[rid],
        expires_at=time.time() + 3600,
    )
    raw = json.dumps(body).encode()
    out = c.post("/api/v1/webhooks/trigger", content=raw, headers=signed(raw, secret))
    assert out.status_code == 201, out.text
    run = api._worker_hub.compute_runs[rid]
    assert len(run.checkpoints) == 1
    aid = run.last_checkpoint_artifact_id
    assert (
        api._engine.artifacts[aid]["sha256"] == "c" * 64
        and aid not in api._engine.artifact_bytes
    )
    assert (
        c.post(
            "/api/v1/webhooks/trigger", content=raw, headers=signed(raw, secret)
        ).json()["id"]
        == out.json()["id"]
    )
    assert len(run.checkpoints) == 1


def test_new_routes_json_schema_and_stream_reconnect_revocation(env, monkeypatch):
    import types
    import fanout.router as router
    from jsonschema import Draft202012Validator, FormatChecker

    c, h, s, p, _ = env

    def validate(response):
        from contract_wire import operation

        op = operation(response.request.url.path, response.request.method)
        schema = (
            (op or {})
            .get("responses", {})
            .get(str(response.status_code), {})
            .get("content", {})
            .get("application/json", {})
            .get("schema")
        )
        if schema:
            response.read()
            Draft202012Validator(
                {"components": CONTRACT["components"], **schema},
                format_checker=FormatChecker(),
            ).validate(response.json())

    c.event_hooks["response"] = [validate]
    assert c.get("/api/v1/recipes", headers=h).status_code == 200
    plan = create(env, intent("wechat", ["reminder"]))
    assert c.get("/api/v1/fanouts", headers=h).status_code == 200
    assert c.get("/api/v1/fanouts/" + plan["id"], headers=h).status_code == 200
    ticks = []

    async def fast_sleep(seconds):
        ticks.append(seconds)

    monkeypatch.setattr(router, "asyncio", types.SimpleNamespace(sleep=fast_sleep))
    stream = c.get("/api/v1/fanouts/" + plan["id"] + "/stream", headers=h)
    assert stream.status_code == 200 and stream.text.count("event: fanout") == 1
    assert s.streams[p.sub] == 0
    cursor = next(
        line[4:] for line in stream.text.splitlines() if line.startswith("id: ")
    )
    replay = c.get(
        "/api/v1/fanouts/" + plan["id"] + "/stream",
        headers={**h, "Last-Event-ID": cursor},
    )
    assert "event: fanout" not in replay.text
    assert "keepalive" in replay.text
    from auth import jwt

    jti = jwt.decode(h["Authorization"][7:], options={"verify_signature": False})["jti"]

    async def revoke(seconds):
        api._validator.revocations.revoke(jti)

    monkeypatch.setattr(router, "asyncio", types.SimpleNamespace(sleep=revoke))
    stream = c.get("/api/v1/fanouts/" + plan["id"] + "/stream", headers=h)
    assert "event: authorization_lost" in stream.text
    assert s.streams[p.sub] == 0


def test_plan_tamper_and_worker_target_grants_cannot_bypass_gate(
    env, tmp_path, monkeypatch
):
    c, h, s, p, _ = env
    plan = create(env)
    s.engine.tasks[plan["task_id"]].args_redacted["plan_hash"] = "tampered"
    with pytest.raises(TaskEngineError):
        s.decide(plan["id"], p, "approved")
    live = s.create(
        intent("wechat", ["reminder"], mode="LIVE"), p, "live-other-intent"
    )[0]
    config = tmp_path / "grants.json"
    config.write_text(
        json.dumps(
            {
                "grants": [
                    {
                        "enabled": True,
                        "owner_sub": p.sub,
                        "target": "reminders",
                        "recipes": ["wechat"],
                        "worker_ids": ["approved-relay"],
                    }
                ]
            }
        )
    )
    monkeypatch.setenv("MWCP_FANOUT_GRANTS_FILE", str(config))
    # Restore the original admitted bytes before checking an independent LIVE grant.
    s.engine.tasks[plan["task_id"]].args_redacted["plan_hash"] = plan["plan_hash"]
    assert not s.claim("unapproved-relay", ["fanout.reminders"], mode="LIVE")
    got = s.claim("approved-relay", ["fanout.reminders"], mode="LIVE")
    assert len(got) == 1 and got[0]["plan_id"] == live["id"]


def test_changed_resource_and_child_payload_fail_before_execution(
    env, monkeypatch, tmp_path
):
    _, _, s, p, _ = env
    plan = create(env, intent("wechat", ["reminder"]))
    child = s.engine.tasks[plan["deliveries"][0]["task_id"]]
    child.args_redacted["step_id"] = "tampered"
    with pytest.raises(TaskEngineError, match="payload_tampered"):
        s.claim("relay", ["fanout.reminders"])
    assert s.deliveries[plan["delivery_ids"][0]]["attempts"] == 0
    child.args_redacted["step_id"] = "reminder"
    from registry import RegistryService

    RegistryService(s.store).disable("fanout-control-plane")
    with pytest.raises(TaskEngineError, match="fanout_resource_changed"):
        s.claim("relay", ["fanout.reminders"])
    path = tmp_path / "bad-grants.json"
    path.write_text('{"grants":[null]}')
    monkeypatch.setenv("MWCP_FANOUT_GRANTS_FILE", str(path))
    assert not s.live_granted(s.plans[plan["id"]], "reminders", "relay")


def test_v2_operations_and_schemas_preserved_except_explicit_optional_entry_extensions():
    import yaml

    old = yaml.safe_load(
        (
            Path(__file__).parents[2] / "contracts/snapshots/v2.0.1/openapi.yaml"
        ).read_text()
    )
    for path, operations in old["paths"].items():
        for method, operation in operations.items():
            if path == "/api/v1/work-items/{id}/dispatch" and method == "post":
                active = copy.deepcopy(CONTRACT["paths"][path][method])
                for branch in [
                    active["requestBody"]["content"]["application/json"],
                    active["responses"]["202"]["content"]["application/json"],
                ]:
                    name = branch["schema"]["$ref"].rsplit("/", 1)[-1]
                    branch["schema"] = CONTRACT["components"]["schemas"][name]["oneOf"][
                        0
                    ]
                assert active == operation
            else:
                assert CONTRACT["paths"][path][method] == operation
    for name, schema in old["components"]["schemas"].items():
        active = copy.deepcopy(CONTRACT["components"]["schemas"][name])
        if name in {"ConversationMessage", "ConversationMessageCreate"}:
            active["properties"].pop("fanout")
        assert active == schema, name
