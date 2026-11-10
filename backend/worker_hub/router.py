"""Worker Hub & Compute V2 FastAPI Router (Workflow 4)."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse

import auth as auth_mod
from auth import Principal
from contract_wire import error_response
from deps import get_principal
from taskengine import TaskEngineError
from worker_hub.service import WorkerHubService


def build_worker_hub_router(worker_hub: WorkerHubService) -> APIRouter:
    router = APIRouter()

    def _require_scope(p: Principal, scope: str) -> None:
        if not p.has_scope(scope):
            raise HTTPException(status_code=403, detail={"error": "forbidden"})

    @router.post("/api/v1/nodes/register")
    def register_node(
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.role != "admin":
            return error_response(403, "admin_required")
        try:
            out = worker_hub.register_node(body, actor=principal.sub)
        except PermissionError as e:
            return error_response(403, str(e))
        except FileExistsError as e:
            return error_response(409, str(e))
        except ValueError as e:
            return error_response(400, str(e))
        return JSONResponse(out, status_code=201)

    @router.post("/api/v1/nodes/{id}/revoke")
    def revoke_node(
        id: str,
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.role != "admin":
            return error_response(403, "admin_required")
        try:
            return worker_hub.revoke_node(id, actor=principal.sub)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})

    @router.post("/api/v1/devices/pair/init")
    def init_device_pair(
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.typ != "actor":
            return error_response(403, "actor_required")
        try:
            out = worker_hub.init_pairing(body, actor=principal.sub)
        except PermissionError as e:
            return error_response(403, str(e))
        except ValueError as e:
            return error_response(400, str(e))
        return JSONResponse(out, status_code=201)

    @router.post("/api/v1/devices/pair/confirm")
    def confirm_device_pair(
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        try:
            return worker_hub.confirm_pairing(body, actor=principal.sub)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionError as e:
            return error_response(403, str(e))
        except (FileExistsError, ValueError) as e:
            return error_response(409, str(e))

    @router.post("/api/v1/workers/{worker_id}/tasks/{task_id}/progress")
    def worker_progress(
        worker_id: str,
        task_id: str,
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        auth_mod.require_worker_path_match(principal, worker_id)
        _require_scope(principal, "worker:claim")
        try:
            return worker_hub.report_progress(
                worker_id,
                task_id,
                generation=int(body["generation"]),
                lease_token=body["lease_token"],
                progress_percent=int(body["progress_percent"]),
                summary=body["summary"],
            )
        except TaskEngineError as e:
            return error_response(e.status, e.code)

    @router.post("/api/v1/compute/runs")
    def create_compute_run(
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        try:
            out = worker_hub.create_compute_run(body, actor=principal.sub)
        except ValueError as e:
            return error_response(400, str(e))
        return JSONResponse(out, status_code=201)

    @router.get("/api/v1/compute/runs/{id}")
    def get_compute_run(
        id: str,
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "registry:read")
        try:
            return worker_hub.get_compute_run(id)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})

    @router.post("/api/v1/compute/runs/{id}/checkpoint")
    def checkpoint_compute_run(
        id: str,
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        try:
            return worker_hub.record_checkpoint(id, body, actor=principal.sub)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except ValueError as e:
            return error_response(400, str(e))

    return router
