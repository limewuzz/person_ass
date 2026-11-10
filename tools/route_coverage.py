"""Static route census paired with runtime test_all_43_operations_validate_against_shared_frozen_contract."""

import os, secrets
import sys, json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
os.environ.pop("MWCP_AUTH_SECRETS_FILE", None)
os.environ["MWCP_AUTH_SECRETS"] = "dev-1:" + secrets.token_hex(32)
import app
from contract_wire import CONTRACT

expected = {
    (m.upper(), p)
    for p, ops in CONTRACT["paths"].items()
    for m in ops
    if m in {"get", "post", "put", "patch", "delete"}
}
from fastapi.openapi.utils import get_openapi

runtime = get_openapi(
    title=app.app.title, version=app.app.version, routes=app.app.routes
)
actual = {
    (method.upper(), path)
    for path, ops in runtime["paths"].items()
    if path.startswith("/api/")
    for method in ops
    if method in {"get", "post", "put", "patch", "delete"}
}
result = {
    "paths": len(CONTRACT["paths"]),
    "operations": len(expected),
    "missing": sorted(expected - actual),
    "unexpected": sorted(actual - expected),
    "runtime_validation_tests": ["backend/tests/test_integrated_wire.py::test_all_43_operations_validate_against_shared_frozen_contract", "backend/tests/test_v2_all_workflows.py::test_all_52_v2_operations_validate_against_frozen_openapi_schema"],
}
assert not result["missing"] and not result["unexpected"]
print(json.dumps(result, indent=2))
