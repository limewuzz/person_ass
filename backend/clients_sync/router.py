"""Multi-Platform Client Sync V2 FastAPI Router (Workflow 5)."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse

from auth import Principal
from contract_wire import error_response
from deps import get_principal
from clients_sync.service import ClientSyncService


def build_clients_sync_router(client_sync: ClientSyncService) -> APIRouter:
    router = APIRouter()

    def _require_scope(p: Principal, scope: str) -> None:
        if not p.has_scope(scope):
            raise HTTPException(status_code=403, detail={"error": "forbidden"})

    @router.get("/api/v1/clients/devices")
    def list_devices(principal: Principal = Depends(get_principal)):
        _require_scope(principal, "tasks:read")
        return {
            "items": client_sync.list_devices(principal=principal),
            "next_cursor": None,
        }

    @router.post("/api/v1/clients/devices")
    def register_device(
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.typ != "actor":
            return error_response(403, "actor_required")
        try:
            out = client_sync.register_device(body, owner_sub=principal.sub)
        except PermissionError as e:
            return error_response(403, str(e))
        except ValueError as e:
            return error_response(400, str(e))
        return JSONResponse(out, status_code=201)

    @router.post("/api/v1/clients/devices/{id}/wipe")
    def wipe_device(
        id: str,
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        try:
            return client_sync.wipe_device(id, principal=principal)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionError as e:
            return error_response(403, str(e))

    @router.get("/api/v1/clients/sync")
    def get_sync(principal: Principal = Depends(get_principal)):
        _require_scope(principal, "tasks:read")
        return client_sync.get_sync_state(owner_sub=principal.sub)

    @router.post("/api/v1/clients/sync")
    def post_sync(
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.typ != "actor":
            return error_response(403, "actor_required")
        try:
            return client_sync.update_sync_state(body, owner_sub=principal.sub)
        except PermissionError as e:
            return error_response(403, str(e))
        except FileExistsError as e:
            return error_response(409, str(e))

    @router.get("/api/v1/clients/releases/latest")
    def get_latest_releases(principal: Principal = Depends(get_principal)):
        _require_scope(principal, "registry:read")
        return client_sync.get_release_manifest()

    return router
