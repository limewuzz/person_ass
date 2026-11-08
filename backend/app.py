"""MagicWorkshop Control Plane — 本地 RC 后端（loopback-only）。

模块：auth(R4-R11) + registry/probes(R11) + taskengine + workergw + approvals + queries。
全部数据域为内存 Mock；PG 侧代码见 dbpg/（PG_RUNTIME NOT RUN）。
"""
from __future__ import annotations

import asyncio
import json
import os
import time

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

import auth as auth_mod
import queries as Q
from auth import AuthConfigError, Principal, TokenValidator
from approvals import ApprovalService
from deps import get_principal
from registry import RegistryStore, build_me_router, build_registry_router, seed_audit_baseline
from taskengine import ALLOWED_TRANSITIONS, TASK_STATES, TERMINAL_STATES, TaskEngine, TaskEngineError
from workergw import WorkerGateway

_APP_START = time.time()
_VERSION = os.environ.get("MWCP_VERSION", "1.1.0-local-rc1")

PUBLIC_PATHS = {"/api/v1/health/live", "/api/v1/health/ready", "/docs", "/openapi.json", "/redoc"}

app = FastAPI(
    title="MagicWorkshop Control Plane API",
    version=_VERSION,
    description="本地 RC：41 路径/43 操作（契约 CONTRACT-LOCK.json 冻结）；Mock 数据域。",
)

# ---- 认证装配（fail closed；R4-R11 语义保留）----
_validator: TokenValidator | None = None
try:
    _secrets = auth_mod.load_secrets_from_env()
    if _secrets:
        _validator = TokenValidator(_secrets)
except AuthConfigError:
    _validator = None
_validator_holder = {"validator": _validator}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/") or path in PUBLIC_PATHS:
            return await call_next(request)
        if _validator is None:
            return JSONResponse(status_code=503, content={
                "error": {"code": "auth_misconfigured",
                          "message": "authentication is not configured (fail closed)"}})
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={
                "error": {"code": "unauthorized", "message": "bearer token required"}})
        try:
            request.state.principal = _validator.decode(header[7:].strip())
        except Exception:
            return JSONResponse(status_code=401, content={
                "error": {"code": "unauthorized", "message": "invalid or expired token"}})
        return await call_next(request)


app.add_middleware(AuthMiddleware)

# ---- 域装配（内存 Mock）----
_store = RegistryStore()
seed_audit_baseline(_store)
_engine = TaskEngine()
_gateway = WorkerGateway(_engine)
_approvals = ApprovalService(_engine, clock=time.time)

app.include_router(build_registry_router(_store))
app.include_router(build_me_router(_validator_holder))


def _engine_err(e: TaskEngineError):
    return JSONResponse(status_code=e.status,
                        content={"error": {"code": e.code, "message": str(e)}})


def _require_scope(p: Principal, scope: str) -> None:
    if not p.has_scope(scope):
        raise HTTPException(status_code=403,
                            detail={"error": "forbidden", "reason": f"missing scope {scope}"})


def _paginate(items: list, cursor: str | None, limit: int, key=lambda x: x.get("id", "")):
    items = sorted(items, key=key)
    if cursor:
        ids = [i.get("id") for i in items]
        items = items[ids.index(cursor) + 1:] if cursor in ids else []
    page = items[:limit]
    nxt = page[-1].get("id") if page and len(items) > limit else None
    return {"items": page, "next_cursor": nxt}


# ══════════ Health ══════════

@app.get("/api/v1/health/live")
def health_live() -> dict:
    return {"status": "ok", "component": "control-plane", "version": _VERSION,
            "uptime_seconds": round(time.time() - _APP_START, 3)}


@app.get("/api/v1/health/ready")
def health_ready() -> JSONResponse:
    deps = {"database": "not_connected",  # PG_RUNTIME NOT RUN（诚实状态）
            "auth": "ok" if _validator is not None else "misconfigured",
            "probes": "not_configured", "workers": "mock"}
    ready = all(v == "ok" for v in deps.values())
    return JSONResponse(status_code=200 if ready else 503, content={
        "status": "ok" if ready else "not_ready", "component": "control-plane",
        "version": _VERSION, "dependency_status": deps})


# ══════════ WorkItems ══════════

@app.get("/api/v1/work-items")
def list_work_items(cursor: str | None = Query(None, max_length=300),
                    limit: int = Query(50, le=200),
                    principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:read")
    return _paginate([_engine.work_item_out(w) for w in _engine.work_items.values()],
                     cursor, limit)


@app.post("/api/v1/work-items")
def create_work_item(body: dict = Body(...),
                     principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:write")
    try:
        rec = _engine.create_work_item(
            title=body.get("title", ""), kind=body.get("kind", ""),
            created_by=principal.sub,
            source_system=body.get("source_system"),
            source_external_id=body.get("source_external_id"))
    except TaskEngineError as e:
        return _engine_err(e)
    return _engine.work_item_out(rec)


@app.get("/api/v1/work-items/{id}")
def get_work_item(id: str, principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:read")
    rec = _engine.work_items.get(id)
    if not rec:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return _engine.work_item_out(rec)


# ══════════ Tasks ══════════

@app.get("/api/v1/tasks")
def list_tasks(state: str | None = None, cursor: str | None = Query(None, max_length=300),
               limit: int = Query(50, le=200), principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:read")
    out = [_engine.task_out(t) for t in _engine.tasks.values()
           if state is None or t.state == state]
    return _paginate(out, cursor, limit)


@app.post("/api/v1/tasks")
def create_task(body: dict = Body(...), principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:write")
    try:
        # 风险/审批要求：能力表未接生产 → 本地策略默认 READ 需审批与否由 body 控制，
        # 但 HIGH/CRITICAL 服务端硬拒（不依赖 UI）
        risk = body.get("risk", "READ")
        if risk in ("HIGH", "CRITICAL"):
            return JSONResponse(status_code=403, content={
                "error": {"code": "risk_blocked",
                          "message": "HIGH/CRITICAL tasks are blocked server-side in local RC"}})
        task, replayed = _engine.create_task(
            principal_id=principal.sub,
            capability=body["capability"], capability_version=int(body.get("capability_version", 1)),
            resource_id=body["resource_id"],
            idempotency_key=body.get("idempotency_key") or os.urandom(16).hex(),
            arguments=body.get("arguments", {}),
            origin_channel=body.get("origin", {}).get("channel", "web"),
            origin_external_ref=body.get("origin", {}).get("source_ref"),
            work_item_id=body.get("work_item_id"),
            requires_approval=bool(body.get("requires_approval", False)),
            risk=risk, dry_run=bool(body.get("dry_run", False)))
    except TaskEngineError as e:
        return _engine_err(e)
    if task.requires_approval:
        _approvals.create_for_task(task, risk=task.risk)
    if replayed:
        out = _engine.task_out(task)
        return JSONResponse(status_code=200, content={**out, "replayed": True})
    out = _engine.task_out(task)
    return JSONResponse(status_code=201, content={
        "task_id": task.id, "state": task.state, "trace_id": task.trace_id,
        "poll_url": f"/api/v1/tasks/{task.id}", "replayed": False, **{k: out[k] for k in
        ("capability", "resource_id", "generation")}})


@app.get("/api/v1/tasks/{id}")
def get_task(id: str, principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:read")
    t = _engine.tasks.get(id)
    if not t:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return _engine.task_out(t)


@app.post("/api/v1/tasks/{id}/cancel")
def cancel_task(id: str, principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:write")
    try:
        t = _engine.transition(id, "CANCELED", actor=principal.sub,
                               summary=f"canceled by {principal.sub}")
    except TaskEngineError as e:
        return _engine_err(e)
    return _engine.task_out(t)


@app.get("/api/v1/tasks/{id}/events")
def task_events(id: str, principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:read")
    if id not in _engine.tasks:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return {"items": [_engine.event_out(e) for e in _engine.events.get(id, [])]}


@app.get("/api/v1/tasks/{id}/attempts")
def task_attempts(id: str, cursor: str | None = Query(None, max_length=300),
                  limit: int = Query(50, le=200),
                  principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:read")
    if id not in _engine.tasks:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return _paginate([_engine.attempt_out(a) for a in _engine.attempts.get(id, [])],
                     cursor, limit)


# ══════════ Approvals ══════════

@app.get("/api/v1/approvals")
def list_approvals(state: str | None = None, principal: Principal = Depends(get_principal)):
    _require_scope(principal, "approvals:read")
    return {"items": [_approvals.approval_out(a) for a in _approvals.approvals.values()
                      if state is None or a.state == state]}


@app.get("/api/v1/approvals/{id}")
def get_approval(id: str, principal: Principal = Depends(get_principal)):
    _require_scope(principal, "approvals:read")
    a = _approvals.approvals.get(id)
    if not a:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return _approvals.approval_out(a)


@app.post("/api/v1/approvals/{id}/approve")
def approve(id: str, principal: Principal = Depends(get_principal)):
    _require_scope(principal, "approvals:decide")
    try:
        return _approvals.approval_out(
            _approvals.decide(id, decision="approved", actor=principal.sub))
    except TaskEngineError as e:
        return _engine_err(e)


@app.post("/api/v1/approvals/{id}/reject")
def reject(id: str, principal: Principal = Depends(get_principal)):
    _require_scope(principal, "approvals:decide")
    try:
        return _approvals.approval_out(
            _approvals.decide(id, decision="rejected", actor=principal.sub))
    except TaskEngineError as e:
        return _engine_err(e)


# ══════════ Worker Gateway（path id 必须 == token subject）══════════

@app.post("/api/v1/workers/{worker_id}/heartbeat")
def worker_heartbeat(worker_id: str, body: dict = Body(...),
                     principal: Principal = Depends(get_principal)):
    auth_mod.require_worker_path_match(principal, worker_id)
    return _gateway.heartbeat(worker_id, node_id=body.get("node_id", ""),
                              version=body.get("version", ""),
                              available_capabilities=body.get("available_capabilities", []))


@app.post("/api/v1/workers/{worker_id}/claim")
def worker_claim(worker_id: str, body: dict = Body(...),
                 principal: Principal = Depends(get_principal)):
    auth_mod.require_worker_path_match(principal, worker_id)
    try:
        tasks = _gateway.claim(worker_id, limit=int(body.get("limit", 1)),
                               capabilities=body.get("capabilities"))
    except TaskEngineError as e:
        return _engine_err(e)
    return {"tasks": tasks}


@app.post("/api/v1/workers/{worker_id}/tasks/{task_id}/started")
def worker_started(worker_id: str, task_id: str, body: dict = Body(...),
                   principal: Principal = Depends(get_principal)):
    auth_mod.require_worker_path_match(principal, worker_id)
    try:
        return _gateway.started(worker_id, task_id,
                                 generation=int(body["generation"]),
                                 lease_token=body["lease_token"])
    except TaskEngineError as e:
        return _engine_err(e)


@app.post("/api/v1/workers/{worker_id}/tasks/{task_id}/finish")
def worker_finish(worker_id: str, task_id: str, body: dict = Body(...),
                  principal: Principal = Depends(get_principal)):
    auth_mod.require_worker_path_match(principal, worker_id)
    try:
        return _gateway.finish(worker_id, task_id,
                               generation=int(body["generation"]),
                               lease_token=body["lease_token"],
                               outcome=body["outcome"],
                               result_summary=body.get("result_summary"))
    except TaskEngineError as e:
        return _engine_err(e)


# ══════════ Observability：observations / audit / SSE / history ══════════

@app.get("/api/v1/observations")
def observations(principal: Principal = Depends(get_principal)):
    _require_scope(principal, "probes:read")
    return {"items": Q.observations_from_registry(_store)}


@app.get("/api/v1/audit")
def audit_events(cursor: str | None = Query(None, max_length=300),
                 limit: int = Query(50, le=200),
                 principal: Principal = Depends(get_principal)):
    _require_scope(principal, "admin:read")
    return _paginate(list(_engine.audit_bus), cursor, limit)


@app.get("/api/v1/events")
async def events_sse(last_event_id: str | None = None,
                     principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:read")

    async def gen():
        start = 0
        if last_event_id:
            try:
                start = int(last_event_id.split("-")[1])
            except (IndexError, ValueError):
                start = 0
        # 本地 RC：重放审计流 + 5s 心跳窗口后关闭（客户端带 Last-Event-ID 续传）
        import asyncio
        for ev in _engine.audit_bus[start:start + 100]:
            yield f"id: {ev['id']}\nevent: audit\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
        for _ in range(2):
            await asyncio.sleep(2.5)
            yield f": keepalive {int(time.time())}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@app.get("/api/v1/events/history")
def events_history(cursor: str | None = Query(None, max_length=300),
                   limit: int = Query(50, le=200),
                   principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:read")
    return Q.audit_history(_engine, cursor=cursor, limit=limit)


# ══════════ Artifacts / Integrations ══════════

@app.get("/api/v1/artifacts")
def artifacts(principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:read")
    return {"items": [], "source_meta": Q._meta("unavailable")}


@app.get("/api/v1/artifacts/{id}")
def artifact_detail(id: str, principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:read")
    raise HTTPException(status_code=404, detail={"error": "not_found"})


@app.get("/api/v1/integrations")
def integrations(principal: Principal = Depends(get_principal)):
    _require_scope(principal, "registry:read")
    return {"items": [
        {"id": "int.google-drive", "display_name": "Google Drive（OAuth 已通，会话级）",
         "status": "unavailable", "scope_labels": ["drive.readonly"],
         "last_verified_at": "2026-11-08T15:00:00+08:00"},
        {"id": "int.rakazo", "display_name": "Rakazo（冻结只读）",
         "status": "unavailable", "scope_labels": [], "last_verified_at": None},
    ], "source_meta": Q._meta("mock")}


# ══════════ UI 查询域（1.1 新增十域之七；workflows 等六域见下）══════════

@app.get("/api/v1/ui/bootstrap")
def ui_bootstrap(principal: Principal = Depends(get_principal)):
    return Q.ui_bootstrap(
        principal={"sub": principal.sub, "type": principal.typ, "role": principal.role,
                   "scopes": sorted(principal.scopes)},
        features={
            "tasks": Q.feature_state("enabled", "P2"),
            "approvals": Q.feature_state("enabled", "P2"),
            "workers": Q.feature_state("enabled", "P1"),
            "real_probes": Q.feature_state("disabled", "P2",
                                           "生产白名单为空（by design）"),
            "production_db": Q.feature_state("disabled", "P1-03",
                                             "PG_RUNTIME NOT RUN"),
            "cherry_links": Q.feature_state("enabled", "P1", "仅静态外链，冻结"),
        })


@app.get("/api/v1/dashboard/summary")
def dashboard_summary(principal: Principal = Depends(get_principal)):
    _require_scope(principal, "tasks:read")
    counts: dict = {}
    for t in _engine.tasks.values():
        counts[t.state.lower()] = counts.get(t.state.lower(), 0) + 1
    acounts: dict = {}
    for a in _approvals.approvals.values():
        acounts[a.state] = acounts.get(a.state, 0) + 1
    nodes_payload = []
    for n in _store.nodes.values():
        nodes_payload.append({"id": n.id, "name": n.name, "health": "unknown",
                              "stale": True})
    return Q.dashboard_summary(
        nodes_payload=nodes_payload, task_counts=counts, approval_counts=acounts,
        recent_events=_engine.audit_bus[-10:])


def _display(endpoint_items):
    def handler(principal: Principal = Depends(get_principal)):
        _require_scope(principal, "registry:read")
        return endpoint_items
    return handler


app.add_api_route("/api/v1/workflows", _display(Q.display_record_list(Q.WORKFLOWS)),
                  methods=["GET"])
app.add_api_route("/api/v1/network/links", _display(Q.display_record_list(Q.NETWORK_LINKS)),
                  methods=["GET"])
app.add_api_route("/api/v1/models", _display(Q.display_record_list(Q.MODELS)),
                  methods=["GET"])
app.add_api_route("/api/v1/projects", _display(Q.display_record_list(Q.PROJECTS)),
                  methods=["GET"])
app.add_api_route("/api/v1/compute/runs", _display(Q.display_record_list(Q.COMPUTE_RUNS)),
                  methods=["GET"])
app.add_api_route("/api/v1/knowledge", _display(Q.display_record_list(Q.KNOWLEDGE)),
                  methods=["GET"])
