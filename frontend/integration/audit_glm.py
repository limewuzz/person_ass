"""Independently audit delivered runtime against its unchanged locked OpenAPI.
No external calls; ASGI transport, ephemeral synthetic actor only. Never logs tokens.
"""

import argparse, os, sys, json, secrets, uuid, asyncio
from pathlib import Path
import yaml, httpx
from jsonschema import Draft202012Validator, FormatChecker

p = argparse.ArgumentParser()
p.add_argument("--backend", required=True)
p.add_argument("--output", required=True)
a = p.parse_args()
sys.path.insert(0, a.backend)
secret = secrets.token_hex(32)
os.environ.pop("MWCP_AUTH_SECRETS_FILE", None)
os.environ["MWCP_AUTH_SECRETS"] = "dev-1:" + secret
os.environ["MWCP_PROBE_MODE"] = "test"
import app, auth

contract = yaml.safe_load(
    Path(__file__).resolve().parents[2].joinpath("contracts/openapi.yaml").read_text()
)
root = {"components": contract["components"]}
records = []
token = auth.mint_token(
    secret,
    sub=str(uuid.uuid4()),
    typ="actor",
    role="admin",
    scopes=sorted(auth.ROLE_SCOPES["admin"]),
    jti=str(uuid.uuid4()),
)


def validate(path, method, status, data):
    op = contract["paths"][path][method]
    response = op["responses"].get(str(status))
    if response is None:
        return [
            {
                "path": "/status",
                "validator": "declared_status",
                "message": f"HTTP {status} absent from locked responses",
            }
        ]
    schema = response.get("content", {}).get("application/json", {}).get("schema")
    if not schema:
        return []
    check = Draft202012Validator({**root, **schema}, format_checker=FormatChecker())
    return [
        {
            "path": "/" + "/".join(str(x) for x in e.absolute_path),
            "validator": e.validator,
            "message": e.message[:250],
        }
        for e in check.iter_errors(data)
    ]


async def run():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app.app),
        base_url="http://127.0.0.1",
        headers={"Authorization": "Bearer " + token},
    ) as c:

        async def request(path, template=None, method="get", **kw):
            r = await c.request(method, path, **kw)
            data = r.json()
            errors = validate(template or path, method, r.status_code, data)
            records.append(
                {
                    "path": template or path,
                    "method": method,
                    "status": r.status_code,
                    "valid": not errors,
                    "errors": errors,
                }
            )
            return data

        for path, ops in contract["paths"].items():
            if "get" in ops and "{" not in path and path != "/api/v1/events":
                await request(path)
        for kind in ["nodes", "resources", "agents"]:
            items = (await c.get("/api/v1/" + kind)).json()["items"]
            if items:
                item = next((x for x in items if "cherry" not in str(x).lower()), None)
                if item:
                    await request(
                        "/api/v1/" + kind + "/" + item["id"],
                        "/api/v1/" + kind + "/{id}",
                    )
        wi = await request(
            "/api/v1/work-items",
            method="post",
            json={"title": "Independent synthetic contract audit", "kind": "task"},
        )
        body = {
            "work_item_id": wi["id"],
            "capability": "local.simulate",
            "resource_id": "local-ledger",
            "arguments": {},
            "dry_run": True,
            "origin": {"channel": "web"},
        }
        headers = {"Idempotency-Key": str(uuid.uuid4())}
        t = await request("/api/v1/tasks", method="post", json=body, headers=headers)
        repeated = await request(
            "/api/v1/tasks", method="post", json=body, headers=headers
        )
        same = t.get("task_id", t.get("id")) == repeated.get(
            "task_id", repeated.get("id")
        )
        records.append({"check": "header_idempotency_replay", "valid": same})
        tid = t.get("task_id", t.get("id"))
        for suffix in ["", "/events", "/attempts"]:
            await request(
                "/api/v1/tasks/" + tid + suffix, "/api/v1/tasks/{id}" + suffix
            )
        await request(
            "/api/v1/tasks/" + tid + "/cancel",
            "/api/v1/tasks/{id}/cancel",
            method="post",
        )
    result = {
        "source": "Audited runtime: " + Path(a.backend).resolve().parent.name,
        "contract_sha256": __import__("hashlib")
        .sha256(
            Path(__file__)
            .resolve()
            .parents[2]
            .joinpath("contracts/openapi.yaml")
            .read_bytes()
        )
        .hexdigest(),
        "checks": records,
        "passed": sum(r["valid"] for r in records),
        "failed": sum(not r["valid"] for r in records),
    }
    Path(a.output).write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "checks"}, indent=2))


asyncio.run(run())
