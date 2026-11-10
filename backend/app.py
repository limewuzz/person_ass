"""MagicWorkshop Control Plane — V2 全模块统一服务端（兼容 1.1.1 全部 41 路径 / 43 操作）。

涵盖七条同步工作流：
1. 平台核心 (backend/core/ + auth/registry/taskengine/approvals)
2. AI 基础设施 (backend/ai_hub/)
3. Agent 系统 (backend/agent_os/)
4. 计算资源与 Worker 中心 (backend/worker_hub/ + workergw/probes)
5. 多端客户端同步 (backend/clients_sync/)
6. 数据集成与知识检索 (backend/integrations/)
7. 契约总控与交付验签 (/api/v1/system/contract-meta)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
from fastapi.exceptions import RequestValidationError
from contract_wire import CONTRACT, error_response, identity, actor_uuid, operation, valid_body

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

import auth as auth_mod
import queries as Q
from service_container import get_container, readiness_check
from auth import AuthConfigError, Principal, TokenValidator
from approvals import ApprovalService
from deps import get_principal
from registry import (
    RegistryStore,
    build_me_router,
    build_registry_router,
    seed_audit_baseline,
)
from taskengine import (
    ALLOWED_TRANSITIONS,
    TASK_STATES,
    TERMINAL_STATES,
    TaskEngine,
    TaskEngineError,
)
from workergw import WorkerGateway

# V2 Domain Services & Routers
from core.sessions import SessionManager
from core.router import build_core_v2_router
from ai_hub.service import AIHubService
from ai_hub.router import build_ai_hub_router
from agent_os.service import AgentOSService
from agent_os.router import build_agent_os_router
from worker_hub.service import WorkerHubService
from worker_hub.router import build_worker_hub_router
from clients_sync.service import ClientSyncService
from clients_sync.router import build_clients_sync_router
from integrations.service import IntegrationsService
from integrations.router import build_integrations_router

_APP_START = time.time()
_VERSION = os.environ.get("MWCP_VERSION", "1.1.1-local-integrated")
_OPENAPI_FILE = Path(__file__).resolve().parents[1] / "contracts" / "openapi.yaml"

PUBLIC_PATHS = {
    "/api/v1/health/live",
    "/api/v1/health/ready",
    "/docs",
    "/openapi.json",
    "/redoc",
}

app = FastAPI(
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    title="MagicWorkshop Control Plane API",
    version=_VERSION,
    description="MagicWorkshop V2 统一控制平面服务端（完整兼容 1.1.1 基线并扩展七大工作流）。",
)

# ---- 认证装配（fail closed；R4-R11 语义保留 + V2 HttpOnly Session/CSRF 扩展）----
_validator: TokenValidator | None = None
try:
    _secrets = auth_mod.load_secrets_from_env()
    if _secrets:
        _validator = TokenValidator(_secrets)
except AuthConfigError:
    _validator = None
_validator_holder = {"validator": _validator}
_session_mgr = SessionManager()


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        request.state.trace_id = str(uuid.uuid4())
        if path.startswith("/api/") and path not in PUBLIC_PATHS:
            if _validator is None:
                return error_response(503, "auth_misconfigured", request.state.trace_id)
            header = request.headers.get("Authorization", "")
            cookie_sid = request.cookies.get("mw_session")
            if header.startswith("Bearer "):
                try:
                    request.state.principal = _validator.decode(header[7:].strip())
                except Exception:
                    return error_response(401, "unauthorized", request.state.trace_id)
            elif cookie_sid:
                # Worker endpoints NEVER accept browser cookies (V2-EXT-005 / BFF boundary)
                if path.startswith("/api/v1/workers/"):
                    return error_response(403, "worker_cookie_forbidden", request.state.trace_id)
                sess = _session_mgr.get_valid_session(cookie_sid)
                if sess is None or _validator.revocations.is_revoked(sess.principal.jti):
                    return error_response(401, "unauthorized", request.state.trace_id)
                if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                    csrf = request.headers.get("X-CSRF-Token", "")
                    if not csrf or csrf != sess.csrf_token:
                        return error_response(403, "csrf_validation_failed", request.state.trace_id)
                request.state.principal = sess.principal
            else:
                return error_response(401, "unauthorized", request.state.trace_id)

            if path.startswith("/api/v1/workers/"):
                worker_id = path.split("/")[4]
                principal = request.state.principal
                scope = (
                    "worker:heartbeat"
                    if path.endswith("/heartbeat")
                    else "worker:claim"
                )
                if (
                    principal.typ != "worker"
                    or principal.sub != worker_id
                    or not principal.has_scope(scope)
                ):
                    return error_response(
                        403, "worker_forbidden", request.state.trace_id
                    )
        if request.method in {"POST", "PUT", "PATCH"} and path.startswith("/api/"):
            op = operation(path, request.method)
            if op:
                for param in op.get("parameters", []):
                    if (
                        param.get("in") == "header"
                        and param.get("required")
                        and not request.headers.get(param["name"])
                    ):
                        return error_response(
                            400, "required_header_missing", request.state.trace_id
                        )
                if op.get("requestBody"):
                    try:
                        body = await request.json()
                    except Exception:
                        return error_response(
                            400, "invalid_json", request.state.trace_id
                        )
                    if not valid_body(op, body):
                        return error_response(
                            400, "invalid_request_schema", request.state.trace_id
                        )
        return await call_next(request)


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    code = (
        exc.detail.get("error", "request_failed")
        if isinstance(exc.detail, dict)
        else "request_failed"
    )
    if not isinstance(code, str):
        code = "request_failed"
    return error_response(
        exc.status_code, code, getattr(request.state, "trace_id", None)
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error(request, exc):
    return error_response(
        400, "invalid_request", getattr(request.state, "trace_id", None)
    )


app.add_middleware(AuthMiddleware)

# ---- 域装配（内存 Mock + 七大工作流完整服务集）----
_store = RegistryStore()
seed_audit_baseline(_store)
_engine = TaskEngine()
_approvals = ApprovalService(_engine, clock=time.time)
_gateway = WorkerGateway(
    _engine,
    registry=_store,
    lease_seconds=int(os.environ.get("MWCP_LOCAL_LEASE_SECONDS", "60")),
)
_engine.admitted_generations = {}
_engine.wire_payload_hashes = {}

_ai_hub = AIHubService(_engine)
_agent_os = AgentOSService(store=_store, engine=_engine, approvals=_approvals)
_worker_hub = WorkerHubService(store=_store, engine=_engine, gateway=_gateway)
_client_sync = ClientSyncService(engine=_engine, session_mgr=_session_mgr)
_integrations = IntegrationsService(engine=_engine, store=_store)

app.include_router(build_registry_router(_store))
app.include_router(build_me_router(_validator_holder))


def _engine_err(e):
    return error_response(e.status, e.code)


def _require_scope(p: Principal, scope: str) -> None:
    if not p.has_scope(scope):
        raise HTTPException(
            status_code=403,
            detail={"error": "forbidden", "reason": f"missing scope {scope}"},
        )


def _paginate(
    items: list, cursor: str | None, limit: int, key=lambda x: x.get("id", "")
):
    items = sorted(items, key=key)
    if cursor:
        ids = [i.get("id") for i in items]
        items = items[ids.index(cursor) + 1 :] if cursor in ids else []
    page = items[:limit]
    nxt = page[-1].get("id") if page and len(items) > limit else None
    return {"items": page, "next_cursor": nxt}


# ══════════ Health ══════════


@app.get("/api/v1/health/live")
def health_live():
    return {
        "status": "ok",
        "checked_at": Q._now(),
        "component": "control-plane",
        "version": _VERSION,
        "uptime_seconds": round(time.time() - _APP_START, 3),
    }


@app.get("/api/v1/health/ready")
def health_ready():
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "dependency_not_ready",
                "message": "PostgreSQL and production adapters are not connected",
            },
            "trace_id": str(uuid.uuid4()),
            "status": "not_ready",
            "checked_at": Q._now(),
            "dependency_status": {
                "database": "not_connected",
                "auth": "ok" if _validator else "misconfigured",
                "probes": "not_configured",
                "workers": "mock",
            },
        },
    )


# ══════════ WorkItems ══════════


@app.get("/api/v1/work-items")
def list_work_items(
    cursor: str | None = Query(None, max_length=300),
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
):
    _require_scope(principal, "tasks:read")
    return _paginate(
        [
            _engine.work_item_out(w)
            for w in _engine.work_items.values()
            if principal.role == "admin" or w.created_by == actor_uuid(principal)
        ],
        cursor,
        limit,
    )


@app.post("/api/v1/work-items")
def create_work_item(
    body: dict = Body(...), principal: Principal = Depends(get_principal)
):
    _require_scope(principal, "tasks:write")
    if principal.typ != "actor":
        return error_response(403, "actor_required")
    try:
        rec = _engine.create_work_item(
            title=body["title"],
            kind=body["kind"],
            created_by=actor_uuid(principal),
            source_system=body.get("source_system"),
            source_external_id=body.get("source_external_id"),
            instructions=body.get("instructions"),
            attachments=body.get("attachments"),
        )
    except TaskEngineError as e:
        return _engine_err(e)
    return JSONResponse(_engine.work_item_out(rec), status_code=201)


@app.get("/api/v1/work-items/{id}")
def get_work_item(id: str, principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:read")
    rec = _engine.work_items.get(id)
    if rec is None:
        raise HTTPException(404, detail={"error": "not_found"})
    if principal.role != "admin" and rec.created_by != actor_uuid(principal):
        raise HTTPException(403, detail={"error": "forbidden"})
    return _engine.work_item_out(rec)


def _task_visible(p, task):
    if not task:
        return False
    if not (
        p.typ == "actor"
        and (p.role in {"admin", "approver"} or p.sub == task.principal_id)
    ):
        return False
    resource = _store.resources.get(task.resource_id)
    return (
        resource is not None
        and p.may_access_kind(resource.kind)
        and p.may_access_node(resource.node_id)
    )


def _visible_task(p, identifier):
    task = _engine.tasks.get(identifier)
    if task is None:
        raise HTTPException(404, detail={"error": "not_found"})
    if not _task_visible(p, task):
        raise HTTPException(403, detail={"error": "forbidden"})
    return task


def _visible_approval(p, identifier):
    approval = _approvals.approvals.get(identifier)
    if approval is None:
        raise HTTPException(404, detail={"error": "not_found"})
    _visible_task(p, approval.task_id)
    return approval


def _worker_allowed(principal, task):
    resource = _store.resources.get(task.resource_id)
    return (
        resource is not None
        and principal.may_access_kind(resource.kind)
        and principal.may_access_node(resource.node_id)
    )


def _resource_unchanged(task):
    resource = _store.resources.get(task.resource_id)
    expected = _engine.admitted_generations.get(task.id)
    if (
        resource is None
        or resource.lifecycle_state != "ACTIVE"
        or resource.generation != expected
    ):
        raise TaskEngineError(
            "resource_changed", "approved target authority changed", 409
        )


# ══════════ Tasks ══════════


@app.get("/api/v1/tasks")
def list_tasks(
    state: str | None = None,
    cursor: str | None = Query(None, max_length=300),
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
):
    _require_scope(principal, "tasks:read")
    _approvals.sweep()
    return _paginate(
        [
            _engine.task_out(t)
            for t in _engine.tasks.values()
            if _task_visible(principal, t) and (state is None or t.state == state)
        ],
        cursor,
        limit,
    )


@app.post("/api/v1/tasks")
def create_task(
    request: Request,
    body: dict = Body(...),
    principal: Principal = Depends(get_principal),
):
    _require_scope(principal, "tasks:write")
    if principal.typ != "actor":
        return error_response(403, "actor_required")
    if body.get("risk") in {"HIGH", "CRITICAL"}:
        return error_response(403, "risk_blocked")
    if body["capability"] != "local.simulate" or body["resource_id"] != "local-ledger":
        return error_response(403, "local_simulation_only")
    if body.get("dry_run") is not True:
        return error_response(400, "dry_run_required")
    if set(body["arguments"]) - {"outcome"} or body["arguments"].get(
        "outcome", "SUCCEEDED"
    ) not in {"SUCCEEDED", "FAILED", "NEEDS_RECONCILIATION"}:
        return error_response(400, "invalid_simulation_arguments")
    wi = body.get("work_item_id")
    if wi and (
        wi not in _engine.work_items
        or (
            principal.role != "admin"
            and _engine.work_items[wi].created_by != actor_uuid(principal)
        )
    ):
        return error_response(403, "work_item_forbidden")
    try:
        with _engine._lock, _store._target_lock:
            from taskengine import json_stable

            wire_key = (principal.sub, request.headers.get("Idempotency-Key", ""))
            wire_hash = hashlib.sha256(json_stable(body).encode()).hexdigest()
            previous = getattr(_engine, "wire_payload_hashes", {}).get(wire_key)
            if previous is not None and previous != wire_hash:
                raise TaskEngineError(
                    "idempotency_conflict", "different complete request payload", 409
                )
            resource = _store.resources.get("local-ledger")
            if (
                resource is None
                or resource.lifecycle_state != "ACTIVE"
                or not principal.may_access_kind(resource.kind)
                or not principal.may_access_node(resource.node_id)
            ):
                return error_response(403, "resource_forbidden")
            task, replayed = _engine.create_task(
                principal_id=principal.sub,
                capability="local.simulate",
                capability_version=1,
                resource_id="local-ledger",
                idempotency_key=request.headers.get("Idempotency-Key", ""),
                arguments=body["arguments"],
                origin_channel=body["origin"]["channel"],
                origin_external_ref=body["origin"].get("source_ref"),
                work_item_id=wi,
                requires_approval=True,
                risk="MEDIUM",
                dry_run=True,
            )
            if not hasattr(_engine, "wire_payload_hashes"):
                _engine.wire_payload_hashes = {}
            _engine.wire_payload_hashes[wire_key] = wire_hash
            if not replayed:
                _engine.admitted_generations[task.id] = resource.generation
                _approvals.create_for_task(task, risk="MEDIUM")
    except TaskEngineError as e:
        return _engine_err(e)
    return JSONResponse(
        {
            "task_id": task.id,
            "state": task.state,
            "trace_id": task.trace_id,
            "poll_url": f"/api/v1/tasks/{task.id}",
            "replayed": replayed,
        },
        status_code=202,
    )


@app.get("/api/v1/tasks/{id}")
def get_task(id: str, principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:read")
    _approvals.sweep()
    return _engine.task_out(_visible_task(principal, id))


@app.post("/api/v1/tasks/{id}/cancel")
def cancel_task(id: str, principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:write")
    _visible_task(principal, id)
    try:
        _engine.transition(id, "CANCELED", actor=principal.sub)
    except TaskEngineError as e:
        return _engine_err(e)
    return JSONResponse(_engine.task_out(_engine.tasks[id]), status_code=202)


@app.get("/api/v1/tasks/{id}/events")
def task_events(id: str, principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:read")
    _visible_task(principal, id)
    return {
        "items": [_engine.event_out(e) for e in _engine.events.get(id, [])],
        "next_cursor": None,
    }


@app.get("/api/v1/tasks/{id}/attempts")
def task_attempts(
    id: str,
    cursor: str | None = Query(None, max_length=300),
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
):
    _require_scope(principal, "tasks:read")
    _visible_task(principal, id)
    return {
        **_paginate(
            [_engine.attempt_out(a) for a in _engine.attempts.get(id, [])],
            cursor,
            limit,
        ),
        "source_meta": Q._meta("mock", observed_at=Q._now(), ttl=5),
    }


# ══════════ Approvals ══════════


@app.get("/api/v1/approvals")
def list_approvals(
    state: str | None = None, principal: Principal = Depends(get_principal)
):
    _require_scope(principal, "approvals:read")
    _approvals.sweep()
    return {
        "items": [
            _approvals.approval_out(a)
            for a in _approvals.approvals.values()
            if _task_visible(principal, _engine.tasks.get(a.task_id))
            and (state is None or a.state.upper() == state.upper())
        ],
        "next_cursor": None,
    }


@app.get("/api/v1/approvals/{id}")
def get_approval(id: str, principal: Principal = Depends(get_principal)):
    _require_scope(principal, "approvals:read")
    _approvals.sweep()
    return _approvals.approval_out(_visible_approval(principal, id))


@app.post("/api/v1/approvals/{id}/approve")
def approve(id: str, principal: Principal = Depends(get_principal)):
    _require_scope(principal, "approvals:decide")
    approval = _visible_approval(principal, id)
    try:
        with _engine._lock, _store._target_lock:
            _resource_unchanged(_engine.tasks[approval.task_id])
            return _approvals.approval_out(
                _approvals.decide(id, decision="approved", actor=principal.sub)
            )
    except TaskEngineError as e:
        return _engine_err(e)


@app.post("/api/v1/approvals/{id}/reject")
def reject(id: str, principal: Principal = Depends(get_principal)):
    _require_scope(principal, "approvals:decide")
    approval = _visible_approval(principal, id)
    try:
        with _engine._lock, _store._target_lock:
            _resource_unchanged(_engine.tasks[approval.task_id])
            return _approvals.approval_out(
                _approvals.decide(id, decision="rejected", actor=principal.sub)
            )
    except TaskEngineError as e:
        return _engine_err(e)


# ══════════ Worker Gateway（path id 必须 == token subject）══════════


@app.post("/api/v1/workers/{worker_id}/heartbeat")
def worker_heartbeat(
    worker_id: str,
    body: dict = Body(...),
    principal: Principal = Depends(get_principal),
):
    auth_mod.require_worker_path_match(principal, worker_id)
    _require_scope(principal, "worker:heartbeat")
    if not principal.may_access_node(body.get("node_id")):
        return error_response(403, "worker_node_forbidden")
    return _gateway.heartbeat(
        worker_id,
        node_id=body.get("node_id", ""),
        version=body.get("version", ""),
        available_capabilities=body.get("available_capabilities", []),
    )


@app.post("/api/v1/workers/{worker_id}/claim")
def worker_claim(
    worker_id: str,
    body: dict = Body(...),
    principal: Principal = Depends(get_principal),
):
    auth_mod.require_worker_path_match(principal, worker_id)
    _require_scope(principal, "worker:claim")
    try:
        tasks = _gateway.claim(
            worker_id,
            limit=int(body.get("limit", 1)),
            capabilities=body.get("capabilities"),
            allowed=lambda task: _worker_allowed(principal, task),
        )
    except TaskEngineError as e:
        return _engine_err(e)
    return {"tasks": tasks}


@app.post("/api/v1/workers/{worker_id}/tasks/{task_id}/started")
def worker_started(
    worker_id: str,
    task_id: str,
    body: dict = Body(...),
    principal: Principal = Depends(get_principal),
):
    auth_mod.require_worker_path_match(principal, worker_id)
    _require_scope(principal, "worker:claim")
    task = _engine.tasks.get(task_id)
    if task is None:
        return error_response(404, "not_found")
    if not _worker_allowed(principal, task):
        return error_response(403, "worker_resource_forbidden")
    try:
        return _gateway.started(
            worker_id,
            task_id,
            generation=int(body["generation"]),
            lease_token=body["lease_token"],
        )
    except TaskEngineError as e:
        return _engine_err(e)


@app.post("/api/v1/workers/{worker_id}/tasks/{task_id}/finish")
def worker_finish(
    worker_id: str,
    task_id: str,
    body: dict = Body(...),
    principal: Principal = Depends(get_principal),
):
    auth_mod.require_worker_path_match(principal, worker_id)
    _require_scope(principal, "worker:claim")
    task = _engine.tasks.get(task_id)
    if task is None:
        return error_response(404, "not_found")
    if not _worker_allowed(principal, task):
        return error_response(403, "worker_resource_forbidden")
    try:
        return _gateway.finish(
            worker_id,
            task_id,
            generation=int(body["generation"]),
            lease_token=body["lease_token"],
            outcome=body["outcome"],
            result_summary=body.get("result_summary"),
        )
    except TaskEngineError as e:
        return _engine_err(e)


# ══════════ Observability：observations / audit / SSE / history ══════════


@app.get("/api/v1/observations")
def observations(principal: Principal = Depends(get_principal)):
    _require_scope(principal, "probes:read")
    return {"items": Q.observations_from_registry(_store)}


@app.get("/api/v1/audit")
def audit_events(
    cursor: str | None = Query(None, max_length=300),
    limit: int = Query(50, le=200),
    principal: Principal = Depends(get_principal),
):
    _require_scope(principal, "admin:read")
    return _paginate(list(_engine.audit_bus), cursor, limit)


@app.get("/api/v1/events")
async def events_sse(
    request: Request,
    last_event_id: str | None = None,
    principal: Principal = Depends(get_principal),
):
    _require_scope(principal, "tasks:read")
    cursor = request.headers.get("Last-Event-ID") or last_event_id

    async def gen():
        with _engine._lock:
            entries = list(_engine.audit_bus)
        ids = [e["id"] for e in entries]
        start = ids.index(cursor) + 1 if cursor in ids else 0
        for ev in entries[start : start + 100]:
            if (
                principal.role != "admin"
                and ev["resource_ref"] in _engine.tasks
                and not _task_visible(principal, _engine.tasks[ev["resource_ref"]])
            ):
                continue
            yield f"id: {ev['id']}\nevent: audit\ndata: {json.dumps(ev,ensure_ascii=False)}\n\n"
        yield "retry: 15000\n: local snapshot complete\n\n"

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


@app.get("/api/v1/events/history")
def events_history(
    cursor: str | None = Query(None, max_length=300),
    limit: int = Query(25, ge=1, le=100),
    principal: Principal = Depends(get_principal),
):
    _require_scope(principal, "tasks:read")
    result = Q.audit_history(_engine, cursor=cursor, limit=limit)
    if principal.role != "admin":
        result["items"] = [
            e
            for e in result["items"]
            if e["resource_ref"] in _engine.tasks
            and _task_visible(principal, _engine.tasks[e["resource_ref"]])
        ]
    return result


# ══════════ Artifacts / Integrations ══════════


@app.get("/api/v1/artifacts")
def artifacts(principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:read")
    return {
        "items": [
            a
            for a in _engine.artifacts.values()
            if _task_visible(principal, _engine.tasks.get(a["task_id"]))
        ],
        "next_cursor": None,
    }


@app.get("/api/v1/artifacts/{id}")
def artifact_detail(id: str, principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:read")
    artifact = _engine.artifacts.get(id)
    if artifact is None:
        raise HTTPException(404, detail={"error": "not_found"})
    _visible_task(principal, artifact["task_id"])
    return artifact


@app.get("/api/v1/integrations")
def integrations(principal: Principal = Depends(get_principal)):
    _require_scope(principal, "registry:read")
    return {
        "items": [
            {
                "id": "int.google-drive",
                "display_name": "Google Drive（此控制平面未授权）",
                "status": "UNAVAILABLE",
                "scope_labels": ["drive.readonly"],
                "last_verified_at": "2026-11-08T15:00:00+08:00",
            },
            {
                "id": "int.rakazo",
                "display_name": "Rakazo（冻结只读）",
                "status": "UNAVAILABLE",
                "scope_labels": [],
                "last_verified_at": None,
            },
        ],
        "source_meta": Q._meta("mock"),
    }


# ══════════ UI 查询域（1.1 新增十域之七；workflows 等六域见下）══════════


@app.get("/api/v1/ui/bootstrap")
def ui_bootstrap(principal: Principal = Depends(get_principal)):
    return Q.ui_bootstrap(
        principal={
            "identity": identity(principal),
            "login": {
                "sub": principal.sub,
                "type": principal.typ,
                "role": principal.role,
                "scopes": sorted(principal.scopes),
            },
        },
        features={
            "tasks": Q.feature_state(
                "enabled" if principal.has_scope("tasks:write") else "disabled", "P2"
            ),
            "approvals": Q.feature_state(
                "enabled" if principal.has_scope("approvals:decide") else "disabled",
                "P2",
            ),
            "workers": Q.feature_state("enabled", "P1"),
            "real_probes": Q.feature_state(
                "disabled", "P2", "生产白名单为空（by design）"
            ),
            "production_db": Q.feature_state("disabled", "P1-03", "PG_RUNTIME NOT RUN"),
            "cherry_links": Q.feature_state("enabled", "P1", "仅静态外链，冻结"),
        },
    )


@app.get("/api/v1/dashboard/summary")
def dashboard_summary(principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:read")
    _approvals.sweep()
    counts: dict = {}
    for t in _engine.tasks.values():
        counts[t.state.lower()] = counts.get(t.state.lower(), 0) + 1
    acounts: dict = {}
    for a in _approvals.approvals.values():
        acounts[a.state] = acounts.get(a.state, 0) + 1
    nodes_payload = []
    for n in _store.nodes.values():
        if principal.may_access_node(n.id):
            nodes_payload.append(_store.node_out(n))
    return Q.dashboard_summary(
        nodes_payload=nodes_payload,
        task_counts=counts,
        approval_counts=acounts,
        recent_events=_engine.audit_bus[-10:],
    )


def _display(endpoint_items):
    def handler(principal: Principal = Depends(get_principal)):
        _require_scope(principal, "registry:read")
        return endpoint_items

    return handler


app.add_api_route(
    "/api/v1/workflows", _display(Q.display_record_list(Q.WORKFLOWS)), methods=["GET"]
)
app.add_api_route(
    "/api/v1/network/links",
    _display(Q.display_record_list(Q.NETWORK_LINKS)),
    methods=["GET"],
)
app.add_api_route(
    "/api/v1/models", _display(Q.display_record_list(Q.MODELS)), methods=["GET"]
)
app.add_api_route(
    "/api/v1/projects", _display(Q.display_record_list(Q.PROJECTS)), methods=["GET"]
)
app.add_api_route(
    "/api/v1/compute/runs",
    _display(Q.display_record_list(Q.COMPUTE_RUNS)),
    methods=["GET"],
)
app.add_api_route(
    "/api/v1/knowledge", _display(Q.display_record_list(Q.KNOWLEDGE)), methods=["GET"]
)

# ══════════ V2 七大工作流路由挂载 ══════════

app.include_router(
    build_core_v2_router(
        store=_store,
        engine=_engine,
        approvals=_approvals,
        session_mgr=_session_mgr,
        validator_holder=_validator_holder,
    )
)
app.include_router(build_ai_hub_router(_ai_hub))
app.include_router(build_agent_os_router(_agent_os))
app.include_router(build_worker_hub_router(_worker_hub))
app.include_router(build_clients_sync_router(_client_sync))
app.include_router(build_integrations_router(_integrations))


@app.get("/api/v1/system/contract-meta")
def get_system_contract_meta(principal: Principal = Depends(get_principal)):
    _require_scope(principal, "registry:read")
    total_paths = len(CONTRACT["paths"])
    total_ops = sum(
        1
        for p in CONTRACT["paths"].values()
        for m in p
        if m in {"get", "post", "put", "patch", "delete"}
    )
    return {
        "contract_version": "2.0.0-unified-v2",
        "openapi_sha256": hashlib.sha256(_OPENAPI_FILE.read_bytes()).hexdigest(),
        "total_paths": total_paths,
        "total_operations": total_ops,
        "baseline_v1_paths": 41,
        "baseline_v1_operations": 43,
        "workflows_ready": {
            "platform_core": True,
            "ai_infrastructure": True,
            "agent_os": True,
            "compute_resources": True,
            "multi_platform_clients": True,
            "data_integrations": True,
            "testing_and_delivery": True,
        },
        "checked_at": Q._now(),
    }
