"""Frozen OpenAPI wire helpers. No production credentials or adapters."""

from pathlib import Path
from functools import lru_cache
import uuid, re, yaml
from jsonschema import Draft202012Validator, FormatChecker
from fastapi.responses import JSONResponse

CONTRACT = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "contracts/openapi.yaml").read_text()
)


def actor_uuid(principal):
    try:
        return str(uuid.UUID(principal.sub))
    except ValueError:
        return str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"mw-local:{principal.typ}:{principal.sub}")
        )


def identity(principal):
    return {
        "id": actor_uuid(principal),
        "role": principal.role,
        "display_name": "本地合成演示身份",
        "allowed_scopes": sorted(principal.scopes),
    }


def error_response(status, code, trace=None):
    return JSONResponse(
        {
            "error": {
                "code": code,
                "message": {
                    400: "Invalid request",
                    401: "Authentication required",
                    403: "Access denied",
                    404: "Not found",
                    409: "State conflict",
                    503: "Dependency unavailable",
                }.get(status, "Request failed"),
            },
            "trace_id": trace or str(uuid.uuid4()),
        },
        status_code=status,
    )


def operation(path, method):
    for template, methods in CONTRACT["paths"].items():
        if re.fullmatch(re.sub(r"\{[^}]+\}", r"[^/]+", template), path):
            return methods.get(method.lower())
    return None


@lru_cache(maxsize=64)
def validator(name):
    return Draft202012Validator(
        {"components": CONTRACT["components"], "$ref": "#/components/schemas/" + name},
        format_checker=FormatChecker(),
    )


def valid_body(op, body):
    schema = (
        op.get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema")
    )
    return not schema or not list(
        validator(schema["$ref"].split("/")[-1]).iter_errors(body)
    )
