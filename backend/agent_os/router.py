"""Agent OS V2 FastAPI Router (Workflow 3)."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from auth import Principal
from contract_wire import error_response
from deps import get_principal
from agent_os.service import AgentOSService


def build_agent_os_router(agent_service: AgentOSService) -> APIRouter:
    router = APIRouter()

    def _require_scope(p: Principal, scope: str) -> None:
        if not p.has_scope(scope):
            raise HTTPException(status_code=403, detail={"error": "forbidden"})

    @router.post("/api/v1/agents")
    def upsert_agent(
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.role != "admin":
            return error_response(403, "admin_required")
        try:
            out = agent_service.upsert_agent(body, actor=principal.sub)
        except PermissionError as e:
            return error_response(403, str(e))
        except ValueError as e:
            return error_response(400, str(e))
        return JSONResponse(out, status_code=201)

    @router.patch("/api/v1/agents/{id}")
    def patch_agent(
        id: str,
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.role != "admin":
            return error_response(403, "admin_required")
        try:
            return agent_service.patch_agent(id, body, actor=principal.sub)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionError as e:
            return error_response(403, str(e))
        except ValueError as e:
            return error_response(400, str(e))

    @router.get("/api/v1/conversations")
    def list_conversations(principal: Principal = Depends(get_principal)):
        _require_scope(principal, "tasks:read")
        return {
            "items": agent_service.list_conversations(principal),
            "next_cursor": None,
        }

    @router.post("/api/v1/conversations")
    def create_conversation(
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.typ != "actor":
            return error_response(403, "actor_required")
        try:
            out = agent_service.create_conversation(body, principal=principal)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionError as e:
            return error_response(403, str(e))
        return JSONResponse(out, status_code=201)

    @router.get("/api/v1/conversations/{id}")
    def get_conversation(
        id: str,
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:read")
        try:
            conv = agent_service.require_conversation(id, principal)
            return agent_service.conversation_out(conv)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionError as e:
            return error_response(403, str(e))

    @router.get("/api/v1/conversations/{id}/messages")
    def list_messages(
        id: str,
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:read")
        try:
            return {
                "items": agent_service.list_messages(id, principal),
                "next_cursor": None,
            }
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionError as e:
            return error_response(403, str(e))

    @router.post("/api/v1/conversations/{id}/messages")
    def append_message(
        id: str,
        request: Request,
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.typ != "actor":
            return error_response(403, "actor_required")
        idem_key = request.headers.get("Idempotency-Key", "")
        try:
            out = agent_service.append_message(
                id, body, idempotency_key=idem_key, principal=principal
            )
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionError as e:
            return error_response(403, str(e))
        except FileExistsError as e:
            return error_response(409, str(e))
        except ValueError as e:
            return error_response(400, str(e))
        return JSONResponse(out, status_code=201)

    @router.get("/api/v1/conversations/{id}/stream")
    async def stream_conversation(
        id: str,
        request: Request,
        last_event_id: str | None = None,
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:read")
        cursor = request.headers.get("Last-Event-ID") or last_event_id
        try:
            sse_text = agent_service.stream_conversation_sse(
                id, last_event_id=cursor, principal=principal
            )
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionError as e:
            return error_response(403, str(e))

        async def _gen():
            yield sse_text

        return StreamingResponse(
            _gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @router.post("/api/v1/supervisor/plan")
    def create_supervisor_plan(
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.typ != "actor":
            return error_response(403, "actor_required")
        try:
            out = agent_service.create_supervisor_plan(body, principal=principal)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except ValueError as e:
            return error_response(400, str(e))
        return JSONResponse(out, status_code=201)

    @router.get("/api/v1/plugins")
    def list_plugins(principal: Principal = Depends(get_principal)):
        _require_scope(principal, "registry:read")
        return {
            "items": [agent_service.plugin_out(p) for p in agent_service.plugins.values()],
            "next_cursor": None,
        }

    @router.post("/api/v1/plugins")
    def register_plugin(
        body: dict = Body(...),
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.role != "admin":
            return error_response(403, "admin_required")
        try:
            out = agent_service.register_plugin(body, actor=principal.sub)
        except PermissionError as e:
            return error_response(403, str(e))
        except ValueError as e:
            return error_response(400, str(e))
        return JSONResponse(out, status_code=201)

    @router.post("/api/v1/plugins/{id}/enable")
    def enable_plugin(
        id: str,
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.role != "admin":
            return error_response(403, "admin_required")
        try:
            return agent_service.set_plugin_enabled(id, True, actor=principal.sub)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})

    @router.post("/api/v1/plugins/{id}/disable")
    def disable_plugin(
        id: str,
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.role != "admin":
            return error_response(403, "admin_required")
        try:
            return agent_service.set_plugin_enabled(id, False, actor=principal.sub)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})

    @router.post("/api/v1/plugins/{id}/rollback")
    def rollback_plugin(
        id: str,
        principal: Principal = Depends(get_principal),
    ):
        _require_scope(principal, "tasks:write")
        if principal.role != "admin":
            return error_response(403, "admin_required")
        try:
            return agent_service.rollback_plugin(id, actor=principal.sub)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except ValueError as e:
            return error_response(409, str(e))

    return router
