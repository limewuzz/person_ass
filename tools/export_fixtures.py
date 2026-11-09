"""Explicit fixture export; tests use temp directories and never mutate source artifacts."""

import os, sys, secrets, uuid, json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
secret = secrets.token_hex(32)
os.environ.pop("MWCP_AUTH_SECRETS_FILE", None)
os.environ["MWCP_AUTH_SECRETS"] = "dev-1:" + secret
os.environ["MWCP_PROBE_MODE"] = "test"
import app, auth
from fastapi.testclient import TestClient
from contract_wire import operation, validator

h = {
    "Authorization": "Bearer "
    + auth.mint_token(
        secret,
        sub=str(uuid.uuid4()),
        typ="actor",
        role="admin",
        scopes=sorted(auth.ROLE_SCOPES["admin"]),
        jti=str(uuid.uuid4()),
    )
}
mapping = {
    "ui-bootstrap": "/api/v1/ui/bootstrap",
    "dashboard-summary": "/api/v1/dashboard/summary",
    "events-history": "/api/v1/events/history",
    "workflows": "/api/v1/workflows",
    "models": "/api/v1/models",
    "nodes": "/api/v1/nodes",
    "integrations": "/api/v1/integrations",
    "artifacts": "/api/v1/artifacts",
}
with TestClient(app.app) as c:
    for name, path in mapping.items():
        response = c.get(path, headers=h)
        assert response.status_code == 200
        schema = operation(path, "get")["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"].split("/")[-1]
        assert not list(validator(schema).iter_errors(response.json()))
        (root / "contracts/mock-fixtures" / f"{name}.json").write_text(
            json.dumps(response.json(), ensure_ascii=False, indent=2) + "\n"
        )
print("Exported 8 validated LOCAL_MOCK response fixtures")
