"""Runtime checks against the actual frozen YAML, not shape assertions authored separately."""

import concurrent.futures, json, uuid, time, hashlib, threading
from pathlib import Path
import pytest, httpx
from fastapi.testclient import TestClient
import app as api
from auth import mint_token, ROLE_SCOPES
from contract_wire import CONTRACT, validator
from taskengine import TaskEngine
from approvals import ApprovalService
from workergw import WorkerGateway
from registry import RegistryStore, ResourceRec, RegistryService
import probes

SECRET = "test-secret-only-for-local-tests"


@pytest.fixture()
def context(monkeypatch):
    engine = TaskEngine()
    engine.admitted_generations = {}
    approvals = ApprovalService(engine, clock=time.time)
    gateway = WorkerGateway(engine, registry=api._store)
    monkeypatch.setattr(api, "_engine", engine)
    monkeypatch.setattr(api, "_approvals", approvals)
    monkeypatch.setattr(api, "_gateway", gateway)
    client = TestClient(api.app, raise_server_exceptions=False)
    actor = str(uuid.uuid4())

    def header(sub=actor, role="admin", typ="actor", scopes=None, **kw):
        return {
            "Authorization": "Bearer "
            + mint_token(
                SECRET,
                sub=sub,
                typ=typ,
                role=role,
                scopes=sorted(ROLE_SCOPES[role]) if scopes is None else scopes,
                jti=str(uuid.uuid4()),
                **kw,
            )
        }

    return client, header, engine, approvals, gateway


def body(**updates):
    return {
        "capability": "local.simulate",
        "resource_id": "local-ledger",
        "arguments": {},
        "dry_run": True,
        "origin": {"channel": "web"},
        **updates,
    }


def create(c, h, payload=None, key=None):
    r = c.post(
        "/api/v1/tasks",
        json=payload or body(),
        headers={**h, "Idempotency-Key": key or str(uuid.uuid4())},
    )
    assert r.status_code == 202, r.text
    return r.json()["task_id"]


def check(response, template, method="get"):
    op = CONTRACT["paths"][template][method]
    assert str(response.status_code) in op["responses"], (
        template,
        response.status_code,
    )
    schema = (
        op["responses"][str(response.status_code)]
        .get("content", {})
        .get("application/json", {})
        .get("schema")
    )
    if schema:
        errors = list(
            validator(schema["$ref"].split("/")[-1]).iter_errors(response.json())
        )
        assert not errors, (template, [(list(e.path), e.message) for e in errors])


def test_all_43_operations_validate_against_shared_frozen_contract(context):
    c, header, engine, approvals, gateway = context
    human = header()
    covered = set()

    def get(path, template=None):
        t = template or path.split("?")[0]
        r = c.get(path, headers=human)
        check(r, t)
        covered.add(("get", t))
        return r

    def post(path, data=None, h=None, template=None, key=None):
        t = template or path
        r = c.post(
            path,
            json=data,
            headers={**(h or human), **({"Idempotency-Key": key} if key else {})},
        )
        check(r, t, "post")
        covered.add(("post", t))
        return r

    for path, ops in CONTRACT["paths"].items():
        if "get" in ops and "{" not in path and path != "/api/v1/events":
            get(path)
    get("/api/v1/nodes/us-server", "/api/v1/nodes/{id}")
    get("/api/v1/resources/svc.mwcp.portal", "/api/v1/resources/{id}")
    get("/api/v1/agents/agent.rakazo.chief", "/api/v1/agents/{id}")
    wi = post(
        "/api/v1/work-items", {"title": "Local full wire lifecycle", "kind": "task"}
    ).json()["id"]
    get("/api/v1/work-items/" + wi, "/api/v1/work-items/{id}")
    payload = body(work_item_id=wi)
    canceled = post("/api/v1/tasks", payload, key=str(uuid.uuid4())).json()["task_id"]
    post("/api/v1/tasks/" + canceled + "/cancel", template="/api/v1/tasks/{id}/cancel")
    tid = post("/api/v1/tasks", payload, key=str(uuid.uuid4())).json()["task_id"]
    aid = next(a.id for a in approvals.approvals.values() if a.task_id == tid)
    get("/api/v1/tasks/" + tid, "/api/v1/tasks/{id}")
    get("/api/v1/tasks/" + tid + "/events", "/api/v1/tasks/{id}/events")
    get("/api/v1/tasks/" + tid + "/attempts", "/api/v1/tasks/{id}/attempts")
    get("/api/v1/approvals/" + aid, "/api/v1/approvals/{id}")
    post(
        "/api/v1/approvals/" + aid + "/approve",
        template="/api/v1/approvals/{id}/approve",
    )
    worker = header(sub="worker-contract", role="worker", typ="worker")
    post(
        "/api/v1/workers/worker-contract/heartbeat",
        {
            "node_id": "mac-mini",
            "version": "test",
            "available_capabilities": ["local.simulate"],
            "observed_at": "2026-11-08T00:00:00Z",
        },
        worker,
        "/api/v1/workers/{worker_id}/heartbeat",
    )
    claimed = post(
        "/api/v1/workers/worker-contract/claim",
        {"limit": 1, "capabilities": ["local.simulate"]},
        worker,
        "/api/v1/workers/{worker_id}/claim",
    ).json()["tasks"]
    assert len(claimed) == 1
    task = claimed[0]
    assert task["task_id"] == tid and approvals.approvals[aid].state == "consumed"
    lease = {"generation": task["generation"], "lease_token": task["lease_token"]}
    post(
        f"/api/v1/workers/worker-contract/tasks/{tid}/started",
        lease,
        worker,
        "/api/v1/workers/{worker_id}/tasks/{task_id}/started",
    )
    post(
        f"/api/v1/workers/worker-contract/tasks/{tid}/finish",
        {**lease, "outcome": "SUCCEEDED"},
        worker,
        "/api/v1/workers/{worker_id}/tasks/{task_id}/finish",
    )
    artifacts = get("/api/v1/artifacts").json()["items"]
    assert len(artifacts) == 1
    artifact = artifacts[0]
    get("/api/v1/artifacts/" + artifact["id"], "/api/v1/artifacts/{id}")
    assert (
        hashlib.sha256(engine.artifact_bytes[artifact["id"]]).hexdigest()
        == artifact["sha256"]
    )
    assert artifact["byte_size"] == len(engine.artifact_bytes[artifact["id"]])
    other = post("/api/v1/tasks", body(), key=str(uuid.uuid4())).json()["task_id"]
    rejected = next(a.id for a in approvals.approvals.values() if a.task_id == other)
    post(
        "/api/v1/approvals/" + rejected + "/reject",
        template="/api/v1/approvals/{id}/reject",
    )
    stream = get("/api/v1/events")
    assert "event: audit" in stream.text
    for line in stream.text.splitlines():
        if line.startswith("data: "):
            assert not list(validator("AuditEvent").iter_errors(json.loads(line[6:])))
    get("/api/v1/dashboard/summary")
    get("/api/v1/events/history")
    get("/api/v1/audit")
    get("/api/v1/approvals")
    attempts = get(
        "/api/v1/tasks/" + tid + "/attempts", "/api/v1/tasks/{id}/attempts"
    ).json()["items"]
    assert attempts[0]["state"] == "SUCCEEDED"
    expected = {
        (method, path)
        for path, ops in CONTRACT["paths"].items()
        for method in ops
        if method in {"get", "post"}
    }
    assert covered == expected and len(covered) == 43


def test_http_header_idempotency_100_requests_and_full_payload_conflict(context):
    c, header, engine, approvals, _ = context
    headers = {**header(), "Idempotency-Key": str(uuid.uuid4())}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda _: c.post("/api/v1/tasks", headers=headers, json=body()),
                range(100),
            )
        )
    assert all(r.status_code == 202 for r in results)
    assert (
        len({r.json()["task_id"] for r in results}) == 1
        and sum(not r.json()["replayed"] for r in results) == 1
    )
    assert len(engine.tasks) == len(approvals.approvals) == 1
    r = c.post(
        "/api/v1/tasks", headers=headers, json=body(arguments={"outcome": "FAILED"})
    )
    assert r.status_code == 409
    check(r, "/api/v1/tasks", "post")
    r = c.post(
        "/api/v1/tasks", headers=headers, json=body(unused_optional_context="different")
    )
    assert r.status_code == 409
    assert c.post("/api/v1/tasks", headers=header(), json=body()).status_code == 400


def test_idor_feature_gates_worker_scope_and_no_parameter_downgrade(context):
    c, header, engine, approvals, _ = context
    owner = header(role="operator")
    tid = create(c, owner)
    outsider = header(sub=str(uuid.uuid4()), role="viewer")
    for suffix in ["", "/events", "/attempts"]:
        r = c.get("/api/v1/tasks/" + tid + suffix, headers=outsider)
        assert r.status_code == 403
        assert tid not in r.text
    assert c.get("/api/v1/tasks", headers=outsider).json()["items"] == []
    bootstrap = c.get("/api/v1/ui/bootstrap", headers=outsider).json()
    assert bootstrap["features"]["tasks"]["status"] == "DISABLED"
    worker = header(sub="worker-empty", role="worker", typ="worker", scopes=[])
    assert (
        c.post(
            "/api/v1/workers/worker-empty/claim", json={"limit": 1}, headers=worker
        ).status_code
        == 403
    )
    for changed in [
        body(resource_id="svc.us.rakazo"),
        body(capability="task.shell.exec"),
        body(dry_run=False),
        body(arguments={"cmd": "never execute"}),
    ]:
        assert c.post(
            "/api/v1/tasks",
            headers={**header(), "Idempotency-Key": str(uuid.uuid4())},
            json=changed,
        ).status_code in {400, 403}
    r = c.post(
        "/api/v1/tasks",
        headers={**header(), "Idempotency-Key": str(uuid.uuid4())},
        json=body(requires_approval=False, risk="READ"),
    )
    assert r.status_code == 202 and r.json()["state"] == "WAITING_APPROVAL"


def test_expiry_and_cancel_invalidate_approvals_and_replay_does_not_recreate(context):
    c, header, engine, approvals, _ = context
    h = header()
    key = str(uuid.uuid4())
    tid = create(c, h, key=key)
    a = next(a for a in approvals.approvals.values() if a.task_id == tid)
    assert a.expires_at - time.time() > 590
    a.expires_at = 0
    assert c.get("/api/v1/tasks/" + tid, headers=h).json()["state"] == "EXPIRED"
    assert (
        c.post("/api/v1/approvals/" + a.id + "/approve", headers=h).status_code == 409
    )
    r = c.post("/api/v1/tasks", headers={**h, "Idempotency-Key": key}, json=body())
    assert r.json()["replayed"] is True and len(approvals.approvals) == 1
    tid2 = create(c, h)
    a2 = next(a for a in approvals.approvals.values() if a.task_id == tid2)
    assert c.post("/api/v1/tasks/" + tid2 + "/cancel", headers=h).status_code == 202
    assert (
        a2.state == "expired"
        and c.post("/api/v1/approvals/" + a2.id + "/approve", headers=h).status_code
        == 409
    )


def test_last_event_id_resume_and_cursor_no_replay(context):
    c, header, engine, _, _ = context
    h = header()
    create(c, h)
    events = list(engine.audit_bus)
    cursor = events[0]["id"]
    text = c.get("/api/v1/events", headers={**h, "Last-Event-ID": cursor}).text
    returned = [
        json.loads(x[6:])["id"] for x in text.splitlines() if x.startswith("data: ")
    ]
    assert returned == [e["id"] for e in events[1:]]
    page = c.get("/api/v1/events/history?limit=1", headers=h).json()
    page2 = c.get(
        "/api/v1/events/history", params={"cursor": page["next_cursor"]}, headers=h
    ).json()
    assert page["items"][0]["id"] not in {e["id"] for e in page2["items"]}


def test_public_authority_write_at_final_revision_read_is_rejected(monkeypatch):
    monkeypatch.setenv("MWCP_PROBE_MODE", "test")
    store = RegistryStore()
    rid = "synthetic-only"
    rec = ResourceRec(rid, "service", "owner-a", "synthetic", None)
    store.resources[rid] = rec
    probes.register_target(
        store,
        probes.ProbeTarget(resource_id=rid, url="http://127.0.0.1:18129/synthetic"),
        allow_loopback=True,
    )
    start = threading.Event()
    done = threading.Event()
    rejected = []
    read = ResourceRec.write_rev

    def final_read(self):
        value = read(self)
        if self is rec and store._target_lock.locked():
            start.set()
            assert done.wait(2)
        return value

    monkeypatch.setattr(ResourceRec, "write_rev", final_read)

    def writer():
        assert start.wait(2)
        try:
            rec.owner_system = "owner-b"
        except AttributeError:
            rejected.append(True)
        done.set()

    t = threading.Thread(target=writer)
    t.start()
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200)), trust_env=False
    ) as client:
        probes.run_probe_by_id(store, rid, client=client, allow_loopback=True)
    t.join(2)
    assert not t.is_alive() and rejected and rec.owner_system == "owner-a"
    assert (
        rec.base_health == "healthy"
    )  # valid observation for unchanged owner; rejected writer cannot change authority
    RegistryService(store).transfer_owner(rid, "owner-b")
    assert rec.base_health == "unknown"


def test_resource_generation_and_approval_parameter_tamper_prevent_claim(context):
    c, header, engine, approvals, gateway = context
    h = header()
    tid = create(c, h)
    a = next(a for a in approvals.approvals.values() if a.task_id == tid)
    engine.tasks[tid].args_redacted["outcome"] = "FAILED"
    r = c.post("/api/v1/approvals/" + a.id + "/approve", headers=h)
    assert r.status_code == 409
    assert engine.tasks[tid].state == "WAITING_APPROVAL"
    tid2 = create(c, h)
    a2 = next(a for a in approvals.approvals.values() if a.task_id == tid2)
    assert (
        c.post("/api/v1/approvals/" + a2.id + "/approve", headers=h).status_code == 200
    )
    service = RegistryService(api._store)
    old = api._store.resources["local-ledger"].owner_system
    try:
        service.transfer_owner("local-ledger", "new-owner")
        gateway.heartbeat(
            "controlled",
            node_id="mac-mini",
            version="test",
            available_capabilities=["local.simulate"],
        )
        claimed = gateway.claim("controlled", limit=5, capabilities=["local.simulate"])
        assert not claimed and engine.tasks[tid2].state == "NEEDS_RECONCILIATION"
    finally:
        service.transfer_owner("local-ledger", old)


def test_work_item_source_dedup_is_actor_scoped(context):
    c, header, _, _, _ = context
    payload = {
        "title": "private synthetic work item",
        "kind": "task",
        "source_system": "local",
        "source_external_id": "same-source-ref",
    }
    a = c.post("/api/v1/work-items", headers=header(role="operator"), json=payload)
    outsider = header(sub=str(uuid.uuid4()), role="operator")
    b = c.post("/api/v1/work-items", headers=outsider, json=payload)
    assert a.status_code == b.status_code == 201 and a.json()["id"] != b.json()["id"]
    assert (
        c.get("/api/v1/work-items/" + a.json()["id"], headers=outsider).status_code
        == 403
    )


def test_generation_change_without_new_lease_rejects_finish_and_no_artifact(context):
    _, _, engine, approvals, gateway = context
    t, _ = engine.create_task(
        principal_id="synthetic",
        capability="local.simulate",
        capability_version=1,
        resource_id="local-ledger",
        idempotency_key="generation-only-test",
        arguments={},
        dry_run=True,
    )
    engine.admitted_generations[t.id] = api._store.resources["local-ledger"].generation
    gateway.heartbeat(
        "test-generation",
        node_id="mac-mini",
        version="test",
        available_capabilities=["local.simulate"],
    )
    lease = gateway.claim("test-generation", limit=1)[0]
    gateway.started(
        "test-generation",
        t.id,
        generation=lease["generation"],
        lease_token=lease["lease_token"],
    )
    engine.bump_generation(t.id)
    from taskengine import TaskEngineError

    with pytest.raises(TaskEngineError, match="generation changed"):
        gateway.finish(
            "test-generation",
            t.id,
            generation=lease["generation"],
            lease_token=lease["lease_token"],
            outcome="SUCCEEDED",
        )
    assert t.state == "RUNNING" and not engine.artifacts


def test_worker_capability_filter_and_node_scope_are_enforced(context):
    c, header, engine, approvals, gateway = context
    h = header()
    tid = create(c, h)
    aid = next(a.id for a in approvals.approvals.values() if a.task_id == tid)
    assert c.post("/api/v1/approvals/" + aid + "/approve", headers=h).status_code == 200
    gateway.heartbeat(
        "other-capability",
        node_id="mac-mini",
        version="test",
        available_capabilities=["unrelated.capability"],
    )
    assert (
        gateway.claim("other-capability", limit=1, capabilities=["local.simulate"])
        == []
        and engine.tasks[tid].state == "QUEUED"
    )
    worker = header(
        sub="node-restricted", role="worker", typ="worker", node_ids=["us-server"]
    )
    denied = c.post(
        "/api/v1/workers/node-restricted/heartbeat",
        headers=worker,
        json={
            "node_id": "mac-mini",
            "version": "test",
            "available_capabilities": ["local.simulate"],
            "observed_at": "2026-11-08T00:00:00Z",
        },
    )
    assert denied.status_code == 403


def test_observation_requires_current_target_and_registration_cannot_seed_healthy():
    store = RegistryStore()
    rec = ResourceRec(
        "synthetic-observe", "service", "test", "synthetic", None, base_health="healthy"
    )
    store.resources[rec.id] = rec
    assert rec.base_health == "unknown"
    with pytest.raises(ValueError, match="approved target"):
        RegistryService(store).observe(
            rec.id,
            health="healthy",
            observed_at="2026-11-08T00:00:00Z",
            received_at="2026-11-08T00:00:00Z",
            ttl_seconds=60,
            source="probe:synthetic",
            expected_generation=rec.generation,
            expected_write_rev=rec.write_rev(),
            expected_target_version=1,
        )
    assert rec.base_health == "unknown"
