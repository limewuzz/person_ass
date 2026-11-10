"""V3 contract endpoints. Browser actors never access worker claim/finish APIs."""

import asyncio, hashlib, json, time
import httpx
from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from auth import Principal
from deps import get_principal
from contract_wire import error_response
from taskengine import TaskEngineError


def build_router(service, gateway, api_app):
    router = APIRouter()

    def check(p, scope):
        if not p.has_scope(scope):
            raise TaskEngineError("forbidden", "forbidden", 403)

    def respond(fn, status=200):
        try:
            return JSONResponse(fn(), status_code=status)
        except TaskEngineError as e:
            return error_response(e.status, e.code)

    @router.get("/api/v1/recipes")
    def recipes(p=Depends(get_principal)):
        return respond(lambda: (check(p, "tasks:read"), service.recipes())[1])

    @router.get("/api/v1/fanouts")
    def plans(p=Depends(get_principal)):
        def run():
            check(p, "tasks:read")
            service.refresh()
            with service.engine._lock:
                return {
                    "items": [
                        service.view(x["id"], p)
                        for x in service.plans.values()
                        if p.role == "admin" or x["owner_sub"] == p.sub
                    ],
                    "revision": service.revision,
                    "next_cursor": None,
                }

        return respond(run)

    @router.post("/api/v1/fanouts")
    def create(request: Request, body: dict = Body(...), p=Depends(get_principal)):
        return respond(
            lambda: (
                check(p, "tasks:write"),
                service.create(body, p, request.headers["Idempotency-Key"])[0],
            )[1],
            201,
        )

    @router.get("/api/v1/fanouts/{id}")
    def detail(id: str, p=Depends(get_principal)):
        return respond(
            lambda: (check(p, "tasks:read"), service.refresh(), service.view(id, p))[2]
        )

    @router.post("/api/v1/fanouts/{id}/decision")
    def decision(id: str, body: dict = Body(...), p=Depends(get_principal)):
        return respond(lambda: service.decide(id, p, body["decision"]))

    @router.post("/api/v1/fanouts/{id}/deliveries/{delivery_id}/reconcile")
    def reconcile(
        id: str, delivery_id: str, body: dict = Body(...), p=Depends(get_principal)
    ):
        return respond(lambda: service.reconcile(id, delivery_id, p, body))

    @router.post("/api/v1/fanouts/{id}/simulate")
    def simulate(id: str, body: dict = Body(...), p=Depends(get_principal)):
        def run():
            check(p, "tasks:write")
            plan = service.require(id, p)
            if plan["mode"] != "SIMULATE":
                raise TaskEngineError("simulation_only", "simulation_only", 403)
            caps = [
                "fanout." + d["target"]
                for d in service.deliveries.values()
                if d["plan_id"] == id
                and (not body.get("target") or d["target"] == body["target"])
            ]
            for item in service.claim(
                "simulation:" + p.sub, caps, 10, mode="SIMULATE", plan_id=id
            ):
                text = json.dumps(
                    {
                        "simulation": True,
                        "delivery_id": item["id"],
                        "target": item["target"],
                    },
                    sort_keys=True,
                ).encode()
                result = {
                    "claim_token": item["claim_token"],
                    "generation": item["generation"],
                    "outcome": body.get("outcome", "SUCCEEDED"),
                    "error_code": "simulated_transient_failure",
                    "receipt": {
                        "sha256": hashlib.sha256(text).hexdigest(),
                        "uri": "mock://fanout/" + item["id"],
                        "source_mode": "MOCK",
                        "byte_size": len(text),
                    },
                }
                service.finish(item["id"], "simulation:" + p.sub, result)
            return service.view(id, p)

        return respond(run)

    @router.post("/api/v1/workers/{worker_id}/outbox/claim")
    def claim(worker_id: str, body: dict = Body(...), p=Depends(get_principal)):
        def run():
            worker = gateway.workers.get(worker_id)
            if (
                not worker
                or not p.may_access_node(worker.node_id)
                or not p.may_access_kind("service")
                or gateway.clock() >= worker.heartbeat_expires_at
            ):
                raise TaskEngineError(
                    "worker_not_registered", "worker_not_registered", 403
                )
            return {
                "items": service.claim(
                    worker_id,
                    worker.available_capabilities,
                    body.get("limit", 1),
                    mode=body["mode"],
                )
            }

        return respond(run)

    @router.post("/api/v1/workers/{worker_id}/outbox/{delivery_id}/finish")
    def finish(
        worker_id: str,
        delivery_id: str,
        body: dict = Body(...),
        p=Depends(get_principal),
    ):
        def run():
            worker = gateway.workers.get(worker_id)
            if (
                not worker
                or not p.may_access_node(worker.node_id)
                or not p.may_access_kind("service")
            ):
                raise TaskEngineError("worker_forbidden", "worker_forbidden", 403)
            return service.finish(delivery_id, worker_id, body)

        return respond(run)

    @router.post("/api/v1/webhooks/trigger")
    def webhook(request: Request, body: dict = Body(...)):
        def run():
            grant = request.state.webhook_grant
            kid, nonce, fp = request.state.webhook_nonce
            if body["recipe_id"] not in grant.get("recipes", []) or body["origin"][
                "channel"
            ] != grant.get("channel"):
                raise TaskEngineError(
                    "webhook_scope_rejected", "webhook_scope_rejected", 403
                )
            if body["recipe_id"] == "checkpoint" and (
                body.get("parameters", {}).get("run_id") not in grant.get("run_ids", [])
                or not time.time() < grant.get("expires_at", 0) <= time.time() + 86400
            ):
                raise TaskEngineError("run_scope_rejected", "run_scope_rejected", 403)
            with service.engine._lock:
                key = (kid, nonce)
                old = service.nonces.get(key)
                if old and old[0] != fp:
                    raise TaskEngineError(
                        "webhook_replay_conflict", "webhook_replay_conflict", 409
                    )
                service.nonces = {
                    k: v for k, v in service.nonces.items() if time.time() - v[1] < 600
                }
                if len(service.nonces) >= 10000:
                    raise TaskEngineError(
                        "webhook_replay_capacity", "webhook_replay_capacity", 503
                    )
                p = Principal(
                    grant["owner_sub"],
                    "actor",
                    "operator",
                    {"tasks:write", "tasks:read"},
                )
                result, _ = service.create(
                    body,
                    p,
                    request.headers["Idempotency-Key"],
                    run_grant=body["recipe_id"] == "checkpoint",
                )
                service.nonces[key] = (fp, time.time())
                return result

        return respond(run, 201)

    @router.get("/api/v1/fanouts/{id}/stream")
    async def stream(id: str, request: Request, p=Depends(get_principal)):
        # Read through the same authenticated ASGI API each poll. No long-lived DB
        # transaction; revocation and cross-process checkpoint changes are revalidated.
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() in {"authorization", "cookie"}
        }
        if service.streams.get(p.sub, 0) >= 4:
            return error_response(503, "stream_limit")
        service.streams[p.sub] = service.streams.get(p.sub, 0) + 1
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api_app, raise_app_exceptions=False),
            base_url="http://127.0.0.1",
            headers=headers,
        )
        try:
            first = await client.get("/api/v1/fanouts/" + id)
        except BaseException:
            await client.aclose()
            service.streams[p.sub] -= 1
            raise
        if first.status_code != 200:
            await client.aclose()
            service.streams[p.sub] -= 1
            return error_response(first.status_code, "stream_unavailable")

        async def events():
            cursor = request.headers.get("Last-Event-ID", "")
            current = first
            try:
                for tick in range(30):
                    if await request.is_disconnected():
                        break
                    if current.status_code != 200:
                        yield "event: authorization_lost\ndata: {}\n\n"
                        break
                    data = current.json()
                    rev = f"{id}:{data['revision']}"
                    if rev != cursor:
                        cursor = rev
                        yield f"id: {rev}\nevent: fanout\ndata: {json.dumps(data,ensure_ascii=False)}\n\n"
                    elif tick % 10 == 0:
                        yield ": keepalive\n\n"
                    await asyncio.sleep(1)
                    current = await client.get("/api/v1/fanouts/" + id)
            finally:
                await client.aclose()
                service.streams[p.sub] = max(0, service.streams.get(p.sub, 1) - 1)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return router
