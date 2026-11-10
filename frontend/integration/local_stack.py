"""Loopback-only session BFF + isolated corrected GLM API. No production credentials.
The BFF validates locked JSON responses; it does NOT rename backend DTOs.
"""

from __future__ import annotations
import argparse, asyncio, hashlib, hmac, ipaddress, json, os, re, secrets, sys, time, uuid
from pathlib import Path
from datetime import datetime, timezone
import httpx, uvicorn, yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from jsonschema import Draft202012Validator, FormatChecker
from starlette.datastructures import MutableHeaders

ROOT = Path(__file__).resolve().parents[1]
contract = yaml.safe_load((ROOT.parent / "contracts/openapi.yaml").read_text())
lock = json.loads((ROOT.parent / "contracts/CONTRACT-LOCK.json").read_text())
assert (
    lock["sha256"]
    == hashlib.sha256((ROOT.parent / "contracts/openapi.yaml").read_bytes()).hexdigest()
)
SESSIONS = {}
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
report = []
secret = secrets.token_hex(32)
actor_id = str(uuid.uuid4())
worker_id = "local-synthetic-worker"
RAW_ORIGIN = "http://127.0.0.1:8127"
WEB_ORIGIN = "http://127.0.0.1:5174"
tokens = {}


def error(status, code):
    return JSONResponse(
        {
            "error": {"code": code, "message": "Local integration request unavailable"},
            "trace_id": str(uuid.uuid4()),
        },
        status_code=status,
    )


class LoopbackBoundary:
    """Pure ASGI boundary: preserve SSE disconnect/cancellation semantics."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        # The ephemeral issuer is not a production login, even behind a proxy.
        try:
            local_peer = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            local_peer = False
        local_hosts = {"127.0.0.1:5174", "localhost:5174", "127.0.0.1:8128", "localhost:8128"}

        async def guarded_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "same-origin"
                headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
            await send(message)

        if not local_peer or request.headers.get("host", "").lower() not in local_hosts:
            return await error(403, "loopback_only")(scope, receive, guarded_send)
        await self.app(scope, receive, guarded_send)


app.add_middleware(LoopbackBoundary)


def lookup(path, method):
    for template, methods in contract["paths"].items():
        if re.fullmatch(re.sub(r"\{[^}]+\}", r"[^/]+", template), path):
            return template, methods.get(method.lower())
    return path, None


def validation(schema, data):
    return list(
        Draft202012Validator(
            {"components": contract["components"], **schema},
            format_checker=FormatChecker(),
        ).iter_errors(data)
    )


@app.post("/local/session")
async def session(request: Request):
    if request.headers.get("origin") != WEB_ORIGIN:
        return error(403, "origin_rejected")
    if callable(tokens.get("actor_factory")):
        tokens["actor"] = tokens["actor_factory"]()
    sid = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    SESSIONS[sid] = {"csrf": csrf, "expires": time.monotonic() + 3600}
    for old in list(SESSIONS):
        if SESSIONS[old]["expires"] < time.monotonic():
            SESSIONS.pop(old)
    r = JSONResponse(
        {
            "mode": "LOCAL_MOCK",
            "csrf": csrf,
            "identity": "Ephemeral local integration actor",
        }
    )
    r.set_cookie(
        "mw_local_session",
        sid,
        httponly=True,
        samesite="strict",
        max_age=3600,
        path="/",
    )
    r.headers["Cache-Control"] = "no-store"
    return r


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(rest: str, request: Request):
    path = "/api/" + rest
    session = SESSIONS.get(request.cookies.get("mw_local_session", ""))
    if not session or session["expires"] < time.monotonic():
        return error(401, "local_session_required")
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.headers.get("origin") != WEB_ORIGIN or not hmac.compare_digest(
            request.headers.get("x-mw-csrf", ""), session["csrf"]
        ):
            return error(403, "csrf_rejected")
    if "/workers/" in path:
        return error(403, "browser_worker_forbidden")
    template, op = lookup(path, request.method)
    if not op:
        return error(404, "unknown_contract_operation")
    if "cherry" in path.lower():
        return error(403, "frozen_catalog_entry")
    body = None
    if request.method in {"POST", "PUT", "PATCH"}:
        body = await request.body()
        schema = (
            op.get("requestBody", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema")
        )
        if schema:
            try:
                data = json.loads(body)
            except ValueError:
                return error(400, "invalid_json")
            if validation(schema, data):
                return error(400, "request_schema_mismatch")
    headers = {
        "Authorization": "Bearer " + tokens["actor"],
        "Content-Type": "application/json",
    }
    if key := request.headers.get("Idempotency-Key"):
        headers["Idempotency-Key"] = key
    if last := request.headers.get("Last-Event-ID"):
        headers["Last-Event-ID"] = last
    try:
        async with httpx.AsyncClient(
            base_url=RAW_ORIGIN, trust_env=False, timeout=10
        ) as client:
            if path == "/api/v1/events" or path.endswith("/stream"):
                # Stream bytes unchanged; same-origin cookie auth stays at BFF, raw bearer stays server-side.
                async def stream():
                    try:
                        async with httpx.AsyncClient(
                            base_url=RAW_ORIGIN, trust_env=False, timeout=15
                        ) as s:
                            async with s.stream("GET", path, headers=headers) as r:
                                if r.status_code != 200:
                                    return
                                async for chunk in r.aiter_bytes():
                                    yield chunk
                    except httpx.HTTPError:
                        return

                return StreamingResponse(
                    stream(),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache"},
                )
            response = await client.request(
                request.method,
                path,
                params=request.query_params,
                headers=headers,
                content=body,
            )
    except httpx.HTTPError:
        return error(503, "local_upstream_offline")
    try:
        data = response.json()
    except ValueError:
        return error(503, "invalid_upstream_json")
    schema = (
        op["responses"]
        .get(str(response.status_code), {})
        .get("content", {})
        .get("application/json", {})
        .get("schema")
    )
    # Ready 503 is intentionally preserved, despite its absence from the locked health response set.
    ready_not_connected = path == "/api/v1/health/ready" and response.status_code == 503
    errors = (
        validation(schema, data)
        if schema
        else (
            []
            if ready_not_connected or str(response.status_code) in op["responses"]
            else ["undeclared_status"]
        )
    )
    report.append(
        {
            "method": request.method,
            "path": template,
            "status": response.status_code,
            "schema_valid": not errors,
        }
    )
    report_path = Path(
        os.environ.get(
            "MW_INTEGRATION_REPORT", str(ROOT / "evidence/integration-http.json")
        )
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))
    if errors:
        return error(
            (
                response.status_code
                if response.status_code in [401, 403, 404, 409]
                else 503
            ),
            "upstream_contract_mismatch",
        )
    if response.status_code == 204 or not response.content:
        return JSONResponse(None, status_code=response.status_code)
    # Cherry has no detail view/probe in new UI; retain only original static history outside this catalog.
    if path in ["/api/v1/services", "/api/v1/resources"] and isinstance(
        data.get("items"), list
    ):
        data["items"] = [
            r for r in data["items"] if "cherry" not in json.dumps(r).lower()
        ]
    return JSONResponse(
        data, status_code=response.status_code, headers={"Cache-Control": "no-store"}
    )


async def synthetic_worker():
    """Only processes local.simulate tasks in this NEW in-memory ledger; never executes commands."""
    await asyncio.sleep(1)
    async with httpx.AsyncClient(
        base_url=RAW_ORIGIN,
        trust_env=False,
        headers={"Authorization": "Bearer " + tokens["worker"]},
    ) as c:
        while True:
            try:
                if callable(tokens.get("worker_factory")):
                    c.headers["Authorization"] = "Bearer " + tokens["worker_factory"]()
                await c.post(
                    f"/api/v1/workers/{worker_id}/heartbeat",
                    json={
                        "node_id": "mac-mini",
                        "version": "local-integration",
                        "available_capabilities": ["local.simulate"],
                        "observed_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                response = await c.post(
                    f"/api/v1/workers/{worker_id}/claim",
                    json={"limit": 1, "capabilities": ["local.simulate"]},
                )
                if response.status_code == 200:
                    for task in response.json()["tasks"]:
                        if (
                            task.get("capability") != "local.simulate"
                            or task.get("resource_id") != "local-ledger"
                        ):
                            continue
                        tid = task.get("task_id", task.get("id"))
                        lease = {
                            "generation": task["generation"],
                            "lease_token": task["lease_token"],
                        }
                        started = await c.post(
                            f"/api/v1/workers/{worker_id}/tasks/{tid}/started",
                            json=lease,
                        )
                        if started.status_code == 200:
                            await asyncio.sleep(0.4)
                            outcome = task.get("arguments", {}).get(
                                "outcome", "SUCCEEDED"
                            )
                            if outcome == "NEEDS_RECONCILIATION":
                                continue  # deliberate local disconnect; lease expiry reconciles, never auto-runs elsewhere
                            await c.post(
                                f"/api/v1/workers/{worker_id}/tasks/{tid}/finish",
                                json={
                                    **lease,
                                    "outcome": outcome,
                                    "result_summary": "LOCAL MOCK · synthetic result; no external action",
                                },
                            )
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1)


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--backend", required=True)
    p.add_argument("--no-worker", action="store_true")
    p.add_argument("--lease-seconds", type=int, default=10)
    a = p.parse_args()
    sys.path.insert(0, str(Path(a.backend).resolve()))
    os.environ.pop("MWCP_AUTH_SECRETS_FILE", None)
    os.environ["MWCP_AUTH_SECRETS"] = "dev-1:" + secret
    os.environ["MWCP_PROBE_MODE"] = "test"
    os.environ["MWCP_LOCAL_LEASE_SECONDS"] = str(a.lease_seconds)
    import app as raw, auth

    tokens["actor"] = auth.mint_token(
        secret,
        sub=actor_id,
        typ="actor",
        role="admin",
        scopes=sorted(auth.ROLE_SCOPES["admin"]),
        ttl_seconds=3600,
        jti=str(uuid.uuid4()),
    )
    tokens["worker"] = auth.mint_token(
        secret,
        sub=worker_id,
        typ="worker",
        role="worker",
        scopes=sorted(auth.ROLE_SCOPES["worker"]),
        ttl_seconds=3600,
        jti=str(uuid.uuid4()),
    )
    tokens["actor_factory"] = lambda: auth.mint_token(
        secret,
        sub=actor_id,
        typ="actor",
        role="admin",
        scopes=sorted(auth.ROLE_SCOPES["admin"]),
        ttl_seconds=3600,
        jti=str(uuid.uuid4()),
    )
    tokens["worker_factory"] = lambda: auth.mint_token(
        secret,
        sub=worker_id,
        typ="worker",
        role="worker",
        scopes=sorted(auth.ROLE_SCOPES["worker"]),
        ttl_seconds=3600,
        jti=str(uuid.uuid4()),
    )
    servers = [
        uvicorn.Server(
            uvicorn.Config(
                raw.app,
                host="127.0.0.1",
                port=8127,
                log_level="warning",
                access_log=False,
            )
        ),
        uvicorn.Server(
            uvicorn.Config(
                app, host="127.0.0.1", port=8128, log_level="warning", access_log=False
            )
        ),
    ]
    jobs = [s.serve() for s in servers]
    if not a.no_worker:
        jobs.append(synthetic_worker())
    await asyncio.gather(*jobs)


if __name__ == "__main__":
    asyncio.run(main())
