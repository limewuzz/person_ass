"""请求级依赖：从中间件放入 request.state 的 Principal 取出。"""
from fastapi import Request

from auth import Principal


def get_principal(request: Request) -> Principal:
    p = getattr(request.state, "principal", None)
    if p is None:  # 中间件未运行（理论上不可达，fail closed 兜底）
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail={"error": "unauthorized"})
    return p
