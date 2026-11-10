"""Platform Core V2 API Router: session lifecycle, controlled Registry mutations, WorkItem dispatch, and Task reconciliation."""
from __future__ import annotations

import hashlib
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from auth import Principal
from contract_wire import actor_uuid, error_response
from deps import get_principal
from registry import RegistryService, ResourceRec, _iso
from taskengine import TaskEngineError, json_stable


def build_core_v2_router(
    *,
    store,
    engine,
    approvals,
    session_mgr,
    validator_holder: dict,
) -> APIRouter:
    router = APIRouter()

    def _require_scope(p: Principal, scope: str) -> None:
        if not p.has_scope(scope):
            raise HTTPException(status_code=403, detail={"error": "forbidden"})

    def _resource_meta_out(rec) -> dict:
        return {
            "resource_id": rec.id,
            "generation": rec.generation,
            "lifecycle_state": rec.lifecycle_state,
            "owner_system": rec.owner_system,
            "node_id": rec.node_id,
            "updated_at": rec.observed_at or _iso(engine._audit_seq + 1700000000),
        }

    # ── Session & Token Revocation ──

    @router.post("/api/v1/auth/session")
    def create_session(
        request: Request,
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        if principal.typ != "actor":
            return error_response(403, "actor_required")
        platform = body.get("client_platform", "web")
        device_id = body.get("device_id")
        rec = session_mgr.create_session(
            principal, client_platform=platform, device_id=device_id
        )
        engine.audit(principal.sub, "auth.session.create", rec.session_id, f"platform={platform}")
        resp = JSONResponse(session_mgr.session_out(rec), status_code=200, headers={"Cache-Control": "no-store"})
        resp.set_cookie(
            key="mw_session",
            value=rec.session_id,
            httponly=True,
            secure=True,
            samesite="strict",
            path="/api",
        )
        resp.set_cookie("mwcp_csrf", rec.csrf_token, secure=True, samesite="strict", path="/")
        return resp

    @router.post("/api/v1/auth/logout")
    def logout_session(
        request: Request,
        principal: Principal = Depends(get_principal),
    ):
        sid = request.cookies.get("mw_session")
        if sid:
            session_mgr.revoke_session(sid)
        validator = validator_holder.get("validator")
        if validator and principal.jti:
            validator.revocations.revoke(principal.jti)
        engine.audit(principal.sub, "auth.session.logout", sid or principal.jti, "revoked")
        resp = JSONResponse(
            {
                "status": "ok",
                "checked_at": _iso(1762732800.0),
                "component": "auth-session",
            },
            status_code=200,
        )
        resp.delete_cookie("mw_session", path="/api")
        resp.delete_cookie("mwcp_csrf", path="/", secure=True, samesite="strict")
        return resp

    @router.post("/api/v1/auth/revoke")
    def revoke_token(
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        if principal.role != "admin" and not principal.has_scope("admin:read"):
            return error_response(403, "admin_required")
        jti = body["jti"]
        validator = validator_holder.get("validator")
        if validator is None:
            return error_response(503, "auth_misconfigured")
        validator.revocations.revoke(jti)
        engine.audit(principal.sub, "auth.token.revoke", jti, body.get("reason") or "manual")
        return {
            "status": "ok",
            "checked_at": _iso(1762732800.0),
            "component": "auth-revocation",
        }

    # ── Controlled Resource Registry Mutations (R11 + V2 Generation CAS) ──

    @router.post("/api/v1/resources")
    def register_resource(
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.role != "admin":
            return error_response(403, "admin_required")
        rid = body["id"]
        if "cherry" in rid.lower() or "cherry" in body["owner_system"].lower():
            return error_response(403, "cherry_frozen_boundary")
        svc = RegistryService(store)
        try:
            rec = svc.register(
                ResourceRec(
                    rid,
                    body["kind"],
                    body["owner_system"],
                    body["display_name"],
                    body.get("node_id"),
                    source="v2-registry-api",
                )
            )
        except ValueError as e:
            return error_response(409, str(e))
        engine.audit(principal.sub, "registry.resource.register", rid, f"gen={rec.generation}")
        return JSONResponse(_resource_meta_out(rec), status_code=201)

    @router.patch("/api/v1/resources/{id}")
    def mutate_resource(
        id: str,
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.role != "admin":
            return error_response(403, "admin_required")
        rec = store.resources.get(id)
        if rec is None:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        expected_gen = int(body["expected_generation"])
        if rec.generation != expected_gen:
            return error_response(409, "generation_conflict")
        svc = RegistryService(store)
        action = body["action"]
        try:
            if action == "transfer_owner":
                if not body.get("new_owner"):
                    return error_response(400, "missing_new_owner")
                rec = svc.transfer_owner(
                    id, body["new_owner"], expected_generation=expected_gen
                )
            elif action == "move_node":
                rec = svc.move_node(
                    id, body.get("new_node_id"), expected_generation=expected_gen
                )
            elif action == "change_kind":
                if not body.get("new_kind"):
                    return error_response(400, "missing_new_kind")
                rec = svc.change_kind(
                    id, body["new_kind"], expected_generation=expected_gen
                )
            elif action == "disable":
                rec = svc.disable(id, expected_generation=expected_gen)
            elif action == "enable":
                svc._change(store.resources[id], {"lifecycle_state": "ACTIVE"}); rec = svc.snapshot(id)
            elif action == "recreate":
                rec = svc.recreate(
                    ResourceRec(
                        id,
                        body.get("new_kind") or rec.kind,
                        body.get("new_owner") or rec.owner_system,
                        body.get("display_name") or rec.display_name,
                        body.get("new_node_id", rec.node_id),
                    )
                )
            else:
                return error_response(400, "unknown_mutation_action")
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except ValueError as e:
            return error_response(409, str(e))
        engine.audit(principal.sub, f"registry.resource.{action}", id, f"gen={rec.generation}")
        return _resource_meta_out(rec)

    @router.delete("/api/v1/resources/{id}")
    def delete_resource(
        id: str,
        expected_generation: int | None = None,
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.role != "admin":
            return error_response(403, "admin_required")
        rec = store.resources.get(id)
        if rec is None:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        svc = RegistryService(store)
        try:
            svc.delete(id, expected_generation=expected_generation)
        except ValueError as e:
            return error_response(409, str(e))
        engine.audit(principal.sub, "registry.resource.delete", id, f"gen={rec.generation}")
        return _resource_meta_out(rec)

    # ── Transactional WorkItem Dispatch & Task Reconciliation ──

    @router.post("/api/v1/work-items/{id}/dispatch")
    def dispatch_work_item(
        id: str,
        request: Request,
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.typ != "actor":
            return error_response(403, "actor_required")
        wi = engine.work_items.get(id)
        if wi is None:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        if principal.role != "admin" and wi.created_by != actor_uuid(principal):
            return error_response(403, "work_item_forbidden")
        if body.get("dry_run") is not True:
            return error_response(400, "dry_run_required")
        cap_name = body["capability"]
        res_id = body["resource_id"]
        if cap_name != "local.simulate" or res_id != "local-ledger":
            return error_response(403, "local_simulation_only")
        idem_key = request.headers.get("Idempotency-Key", "")
        args = body.get("arguments") or {}
        if set(args) - {"outcome"} or args.get("outcome", "SUCCEEDED") not in {
            "SUCCEEDED",
            "FAILED",
            "NEEDS_RECONCILIATION",
        }:
            return error_response(400, "invalid_simulation_arguments")
        try:
            with engine._lock, store._target_lock:
                wire_key = (principal.sub, f"dispatch:{id}:{idem_key}")
                wire_hash = hashlib.sha256(json_stable(body).encode()).hexdigest()
                prev = getattr(engine, "wire_payload_hashes", {}).get(wire_key)
                if prev is not None and prev != wire_hash:
                    return error_response(409, "idempotency_conflict")
                resource = store.resources.get(res_id)
                if (
                    resource is None
                    or resource.lifecycle_state != "ACTIVE"
                    or not principal.may_access_kind(resource.kind)
                    or not principal.may_access_node(resource.node_id)
                ):
                    return error_response(403, "resource_forbidden")
                task, replayed = engine.create_task(
                    principal_id=principal.sub,
                    capability=cap_name,
                    capability_version=1,
                    resource_id=res_id,
                    idempotency_key=idem_key,
                    arguments=args,
                    origin_channel=body.get("origin_channel", "web"),
                    work_item_id=id,
                    requires_approval=True,
                    risk="MEDIUM",
                    dry_run=True,
                )
                engine.wire_payload_hashes[wire_key] = wire_hash
                if not replayed:
                    wi.status = "in_progress"
                    engine.admitted_generations[task.id] = resource.generation
                    approvals.create_for_task(task, risk="MEDIUM")
        except TaskEngineError as e:
            return error_response(e.status, e.code)
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

    @router.post("/api/v1/tasks/{id}/reconcile")
    def reconcile_task(
        id: str,
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        task = engine.tasks.get(id)
        if task is None:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        if principal.role not in {"admin", "approver"} and task.principal_id != principal.sub:
            return error_response(403, "forbidden")
        if task.state != "NEEDS_RECONCILIATION":
            return error_response(409, "task_not_in_reconciliation")
        resolution = body["resolution"]
        reason = body["reason"]
        try:
            with engine._lock:
                engine.transition(
                    id,
                    resolution,
                    actor=principal.sub,
                    summary=f"reconciled->{resolution}: {reason}",
                )
                if resolution == "SUCCEEDED":
                    engine.record_mock_artifact(task)
        except TaskEngineError as e:
            return error_response(e.status, e.code)
        return engine.task_out(task)

    return router
