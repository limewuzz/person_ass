"""AI Hub V2 FastAPI Router (Workflow 2)."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse

import queries as Q
from auth import Principal
from contract_wire import error_response
from deps import get_principal
from ai_hub.service import AIHubService


def build_ai_hub_router(ai_service: AIHubService) -> APIRouter:
    router = APIRouter()

    def _require_scope(p: Principal, scope: str) -> None:
        if not p.has_scope(scope):
            raise HTTPException(status_code=403, detail={"error": "forbidden"})

    @router.get("/api/v1/ai/providers")
    def list_providers(principal: Principal = Depends(get_principal)):
        _require_scope(principal, "registry:read")
        items = [ai_service.provider_out(p) for p in ai_service.providers.values()]
        return {
            "items": items,
            "next_cursor": None,
            "source_meta": Q._meta("mock"),
        }

    @router.post("/api/v1/ai/providers")
    def create_provider(
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.role != "admin":
            return error_response(403, "admin_required")
        try:
            out = ai_service.register_provider(body, actor=principal.sub)
        except PermissionError as e:
            return error_response(403, str(e))
        except FileExistsError as e:
            return error_response(409, str(e))
        except ValueError as e:
            return error_response(400, str(e))
        return JSONResponse(out, status_code=201)

    @router.patch("/api/v1/ai/providers/{id}")
    def patch_provider(
        id: str,
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.role != "admin":
            return error_response(403, "admin_required")
        try:
            return ai_service.update_provider(id, body, actor=principal.sub)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionError as e:
            return error_response(403, str(e))

    @router.delete("/api/v1/ai/providers/{id}")
    def delete_provider(
        id: str,
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.role != "admin":
            return error_response(403, "admin_required")
        try:
            ai_service.delete_provider(id, actor=principal.sub)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        return {
            "status": "ok",
            "checked_at": Q._now(),
            "component": "ai-hub",
        }

    @router.post("/api/v1/ai/providers/{id}/probe")
    def probe_provider(
        id: str,
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        try:
            return ai_service.probe_provider(id, actor=principal.sub)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})

    @router.get("/api/v1/models/{id}")
    def get_model_detail(
        id: str,
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "registry:read")
        try:
            return ai_service.get_model_detail(id)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})

    @router.get("/api/v1/ai/routing-policy")
    def get_routing_policy(principal: Principal = Depends(get_principal)):
        _require_scope(principal, "registry:read")
        return ai_service.get_routing_policy()

    @router.put("/api/v1/ai/routing-policy")
    def put_routing_policy(
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.role != "admin":
            return error_response(403, "admin_required")
        try:
            return ai_service.update_routing_policy(body, actor=principal.sub)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})

    @router.post("/api/v1/ai/completions")
    def create_completion(
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        try:
            return ai_service.run_completion(body, actor=principal.sub)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except ValueError as e:
            return error_response(400, str(e))

    return router
