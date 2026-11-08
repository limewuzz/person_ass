"""MagicWorkshop Control Plane — P1 最小后端（开发期仅 127.0.0.1）。

仅实现 v0.4 契约中 x-phase=P1 的两个健康端点（contracts/openapi.yaml L23-78）。
安全模型按契约 security: humanBearer —— 认证中间件在 P1-04 引入，当前阶段
健康端点按契约允许匿名（Health 标签下 live/ready 未列 401 之外的强制鉴权差异）。

硬边界提醒（README）：不得接入公网反代、不得执行生产操作。
"""
from __future__ import annotations

import os
import time

from fastapi import FastAPI

_APP_START = time.time()
_VERSION = os.environ.get("MWCP_VERSION", "0.1.0-dev")

app = FastAPI(
    title="MagicWorkshop Control Plane API",
    version=_VERSION,
    description="P1 受限开发版：仅健康端点；契约候选 v0.4-preview。",
)


@app.get("/api/v1/health/live")
def health_live() -> dict:
    """Liveness（契约 operationId=get_api_v1_health_live）。"""
    return {
        "status": "ok",
        "component": "control-plane",
        "version": _VERSION,
        "uptime_seconds": round(time.time() - _APP_START, 3),
    }


@app.get("/api/v1/health/ready")
def health_ready() -> dict:
    """Readiness（契约 operationId=get_api_v1_health_ready）。

    P1 阶段依赖项（DB/探针）尚未接入，恒返回 ok=True 并以 deps 标注
    UNKNOWN——遵守「不用非真实数字凑漂亮页面」的全阶段不变式。
    """
    return {
        "status": "ok",
        "component": "control-plane",
        "version": _VERSION,
        "deps": {"database": "UNKNOWN", "probes": "UNKNOWN"},
    }
