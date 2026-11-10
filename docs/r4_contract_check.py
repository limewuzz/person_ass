#!/usr/bin/env python3
"""R4-03 契约核查脚本（机器可读输出；需在 backend/.venv 内运行）。"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"

out: dict = {"files": {}, "counts": {}, "implemented": [], "contract_only": [], "extra": []}

for name in ("openapi.yaml", "worker-protocol.schema.json", "capability.schema.json"):
    p = CONTRACTS / name
    out["files"][name] = hashlib.sha256(p.read_bytes()).hexdigest()

import yaml  # noqa: E402
spec = yaml.safe_load((CONTRACTS / "openapi.yaml").read_text())
paths = spec.get("paths", {})
ops = [m for p in paths.values() for m in p if m in ("get", "post", "put", "delete", "patch")]
out["counts"] = {"paths": len(paths), "operations": len(ops),
                 "x_phase": sum(1 for p in paths.values() for m in p.values()
                                if isinstance(m, dict) and "x-phase" in m)}
assert out["counts"] == {"paths": 79, "operations": 95, "x_phase": 95}, out["counts"]  # V2: 2.0.0-unified-v2 锁定值

sys.path.insert(0, str(ROOT / "backend"))
from fastapi.routing import APIRoute  # noqa: E402
import app as app_mod  # noqa: E402

def _flatten(routes, depth=0):
    """新版 FastAPI include_router 产生 _IncludedRouter 惰性包装，需递归展开。"""
    out = []
    for r in routes:
        if isinstance(r, APIRoute):
            out.append(r.path)
        elif hasattr(r, "original_router") and depth < 5:
            out.extend(_flatten(r.original_router.routes, depth + 1))
        elif hasattr(r, "routes") and depth < 5:
            out.extend(_flatten(r.routes, depth + 1))
    return out

impl = set(_flatten(app_mod.app.routes))
doc_paths = {"/docs", "/redoc", "/openapi.json"}
api_impl = {p for p in impl if p.startswith("/api/")}
out["implemented"] = sorted(api_impl & set(paths))
out["contract_only"] = sorted(set(paths) - api_impl)
out["extra"] = sorted(impl - set(paths) - doc_paths) or "(仅 FastAPI 文档面：/docs /redoc /openapi.json)"

print(json.dumps(out, indent=2, ensure_ascii=False))
