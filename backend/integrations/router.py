"""Data Integrations V2 FastAPI Router (Workflow 6)."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse

from auth import Principal
from contract_wire import error_response
from deps import get_principal
from integrations.service import IntegrationsService


def build_integrations_router(integrations_svc: IntegrationsService) -> APIRouter:
    router = APIRouter()

    def _require_scope(p: Principal, scope: str) -> None:
        if not p.has_scope(scope):
            raise HTTPException(status_code=403, detail={"error": "forbidden"})

    @router.post("/api/v1/uploads/tickets")
    def create_upload_ticket(
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.typ != "actor":
            return error_response(403, "actor_required")
        try:
            out = integrations_svc.create_upload_ticket(body, principal=principal)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionError as e:
            return error_response(403, str(e))
        except ValueError as e:
            return error_response(400, str(e))
        return JSONResponse(out, status_code=201)

    @router.put("/api/v1/uploads/{ticket_id}")
    def put_upload_content(
        ticket_id: str,
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        try:
            return integrations_svc.complete_upload(
                ticket_id, body, principal=principal
            )
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionError as e:
            return error_response(403, str(e))
        except ValueError as e:
            return error_response(400, str(e))

    @router.post("/api/v1/artifacts/{id}/download-ticket")
    def create_download_ticket(
        id: str,
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:read")
        try:
            return integrations_svc.create_download_ticket(id, principal=principal)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionError as e:
            return error_response(403, str(e))

    @router.get("/api/v1/artifacts/{id}/content")
    def get_artifact_content(
        id: str,
        ticket: str | None = None,
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:read")
        try:
            return integrations_svc.get_artifact_content(
                id, ticket_id=ticket, principal=principal
            )
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionError as e:
            return error_response(403, str(e))
        except ValueError as e:
            return error_response(409, str(e))

    @router.post("/api/v1/integrations/{id}/sync")
    def sync_integration(
        id: str,
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        try:
            return integrations_svc.sync_integration(id, body, principal=principal)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionError as e:
            return error_response(403, str(e))
        except ValueError as e:
            return error_response(400, str(e))

    @router.post("/api/v1/knowledge/query")
    def query_knowledge(
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "registry:read")
        return integrations_svc.query_knowledge(body, principal=principal)

    return router
