"""MagicWorkshop Control Plane — P1 后端（开发期仅 127.0.0.1）。

P1-04：认证中间件（Mock OIDC/JWT，fail closed；仅健康探针免认证）。
P1-05：Resource Registry（内存仓储 + 审计基线种子，health=unknown 待真实探针）。

/health/ready 语义（按 P0 评审 §B 修正）：必要依赖未连接时返回 503 + dependency_status，
不用 HTTP 200 冒充 ready。契约 openapi.yaml 当前只声明了 200 —— 该偏差已登记为
待契约修订项 C-1（见 docs/CHANGES-SINCE-P0.md），冻结前需补 503 响应定义。
"""
from __future__ import annotations

import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

import auth as auth_mod
from auth import AuthConfigError, Principal, TokenValidator
from registry import RegistryStore, build_me_router, build_registry_router, seed_audit_baseline

_APP_START = time.time()
_VERSION = os.environ.get("MWCP_VERSION", "0.2.0-dev")

PUBLIC_PATHS = {"/api/v1/health/live", "/api/v1/health/ready", "/docs", "/openapi.json", "/redoc"}

app = FastAPI(
    title="MagicWorkshop Control Plane API",
    version=_VERSION,
    description="P1 受限开发版：认证 + 只读 Registry；契约候选 v0.4-preview。",
)

# ---- 认证装配（fail closed）----
_validator: TokenValidator | None = None
try:
    _secrets = auth_mod.load_secrets_from_env()
    if _secrets:
        _validator = TokenValidator(_secrets)
except AuthConfigError:
    _validator = None

_validator_holder = {"validator": _validator}  # /me 用；可能为 None


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/") or path in PUBLIC_PATHS:
            return await call_next(request)
        if _validator is None:
            return JSONResponse(
                status_code=503,
                content={"error": {"code": "auth_misconfigured",
                                   "message": "authentication is not configured (fail closed)"}},
            )
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"error": {"code": "unauthorized",
                                                                    "message": "bearer token required"}})
        try:
            request.state.principal = _validator.decode(header[7:].strip())
        except Exception:
            return JSONResponse(status_code=401, content={"error": {"code": "unauthorized",
                                                                    "message": "invalid or expired token"}})
        return await call_next(request)


app.add_middleware(AuthMiddleware)

# ---- Registry 装配 ----
_store = RegistryStore()
seed_audit_baseline(_store)
app.include_router(build_registry_router(_store))
app.include_router(build_me_router(_validator_holder))


@app.get("/api/v1/health/live")
def health_live() -> dict:
    """Liveness：仅代表进程活着（200）。"""
    return {
        "status": "ok",
        "component": "control-plane",
        "version": _VERSION,
        "uptime_seconds": round(time.time() - _APP_START, 3),
    }


@app.get("/api/v1/health/ready")
def health_ready() -> JSONResponse:
    """Readiness：必要依赖未连接 → 503 + dependency_status（不冒充 ready）。"""
    deps = {
        "database": "not_connected",  # P1-03 未落地（暂缓中）
        "auth": "ok" if _validator is not None else "misconfigured",
        "probes": "not_configured",
    }
    ready = all(v == "ok" for v in deps.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ok" if ready else "not_ready",
            "component": "control-plane",
            "version": _VERSION,
            "dependency_status": deps,  # 脱敏：只报组件状态，不含任何地址/凭据
        },
    )
