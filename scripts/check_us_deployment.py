"""Anonymous GET-only smoke check for the read-only US static candidate.

Passing this check is not a production identity, database or deployment approval.
No cookies, credentials, Worker requests, redirects or write requests are used.
"""

import argparse
from dataclasses import dataclass
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 1024 * 1024
MAX_ASSETS = 8


@dataclass(frozen=True)
class Response:
    status: int
    content_type: str
    body: bytes
    error: str | None = None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(url: str) -> Response:
    opener = build_opener(NoRedirect())
    request = Request(url, method="GET", headers={
        "User-Agent": "MagicWorkshop-read-only-deployment-check/1.0",
        "Accept-Encoding": "identity",
    })
    try:
        try:
            response = opener.open(request, timeout=15)
        except HTTPError as exc:
            response = exc
        with response:
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                return Response(response.code, "", b"", "ResponseTooLarge")
            if response.headers.get("Content-Encoding", "identity") != "identity":
                return Response(response.code, "", b"", "UnexpectedContentEncoding")
            mime = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            return Response(response.code, mime, data)
    except (URLError, TimeoutError, OSError):
        # Exception text can contain proxy configuration; never print it.
        return Response(0, "", b"", "TransportError")


def validate_origin(origin: str) -> str:
    p = urlsplit(origin)
    if (p.scheme != "https" or not p.hostname or p.username or p.password
            or p.path or p.query or p.fragment or origin != f"https://{p.netloc}"):
        raise ValueError("Use an exact HTTPS origin without credentials, path or query")
    return origin


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []
        self.has_module = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.assets.append(("js", values["src"]))
            self.has_module |= values.get("type") == "module"
        if tag == "link" and "stylesheet" in (values.get("rel") or "").split():
            if values.get("href"):
                self.assets.append(("css", values["href"]))


def json_object(response: Response):
    if response.error or not (response.content_type == "application/json"
                             or response.content_type.endswith("+json")):
        return None
    try:
        value = json.loads(response.body.decode("utf-8"))
    except (ValueError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def inspect_site(origin: str, contract_sha: str, expected_commit=None, transport=fetch):
    validate_origin(origin)
    if expected_commit is not None and not re.fullmatch(r"[a-f0-9]{40}", expected_commit):
        raise ValueError("Expected commit must be a full lowercase Git SHA")
    observations, checks, seen = [], [], {}

    def get(path):
        if path not in seen:
            response = transport(origin + path)
            seen[path] = response
            observations.append({
                "path": path, "status": response.status,
                "content_type": response.content_type, "bytes": len(response.body),
                "sha256": hashlib.sha256(response.body).hexdigest(),
                "error": response.error,
            })
        return seen[path]

    def check(name, passed, requirement):
        checks.append({"name": name, "passed": bool(passed), "requirement": requirement})

    for path, prefix in [("/", "/portal-assets/"), ("/workshop/", "/workshop/assets/")]:
        response = get(path)
        parser = Assets()
        if not response.error and response.content_type == "text/html":
            parser.feed(response.body.decode("utf-8", "replace"))
        valid = (not response.error and response.status == 200
                 and response.content_type == "text/html" and parser.has_module
                 and any(kind == "css" for kind, _ in parser.assets)
                 and len(parser.assets) <= MAX_ASSETS
                 and all(src.startswith(prefix) and not urlsplit(src).netloc
                         and re.fullmatch(re.escape(prefix) + r"[A-Za-z0-9_./-]+", src)
                         and not urlsplit(src).query and not urlsplit(src).fragment
                         and ".." not in src and "%" not in src
                         for _, src in parser.assets))
        check(path + " assets", valid, "HTML with module JS and CSS under " + prefix)
        if valid:
            for kind, src in parser.assets:
                asset = get(src)
                types = {"text/css"} if kind == "css" else {
                    "application/javascript", "text/javascript", "application/x-javascript"}
                # Missing assets must not be served as a SPA HTML fallback.
                check(src, not asset.error and asset.status == 200 and bool(asset.body)
                      and asset.content_type in types
                      and not asset.body.lstrip().lower().startswith((b"<html", b"<!doctype html")),
                      "200 with the asset MIME type and no HTML fallback")

    metadata = get("/workshop/build-meta.json")
    value = json_object(metadata)
    check("build metadata JSON", metadata.status == 200 and value is not None,
          "200 application/json, never a SPA HTML fallback")
    if value is not None:
        required = {"mode": "session", "public_origin": origin,
                    "web_base": "/workshop/", "contract_sha256": contract_sha}
        for field, expected in required.items():
            check("metadata " + field, value.get(field) == expected, "Matches US candidate")
        check("metadata read_only", value.get("read_only") is True, "Boolean true")
        head = value.get("head")
        check("metadata commit", isinstance(head, str)
              and bool(re.fullmatch(r"[a-f0-9]{40}", head))
              and (expected_commit is None or head == expected_commit),
              "Full Git SHA" if expected_commit is None else "Matches expected commit")

    identity = get("/api/v1/me")
    check("anonymous identity denied", identity.status == 401
          and json_object(identity) is not None,
          "401 JSON without any credentials; HTML 200 or implicit admin is a failure")
    passed = all(item["passed"] for item in checks)
    fallback = (metadata.status == 200 and metadata.content_type == "text/html"
                and metadata.body == seen["/"].body)
    return {
        "status": "PUBLIC_READ_ONLY_CANDIDATE_SMOKE_PASSED" if passed else "CHECK_FAILED",
        "failure_kind": None if passed else (
            "LEGACY_SPA_FALLBACK" if fallback else "ROUTING_OR_IDENTITY_MISMATCH"),
        "origin": origin, "checks": checks, "observations": observations,
        "expected_commit": expected_commit, "http_methods": ["GET"],
        "deployed_by_this_check": False, "production_ready": False,
        "unverified_gates": ["authenticated_session", "CSRF_and_Worker_isolation",
                             "PostgreSQL_runtime", "capacity_and_legacy_isolation"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://magicworkshop.fun")
    parser.add_argument("--expected-commit")
    args = parser.parse_args(argv)
    lock = json.loads((ROOT / "contracts/CONTRACT-LOCK.json").read_text())
    sha = hashlib.sha256((ROOT / "contracts/openapi.yaml").read_bytes()).hexdigest()
    if sha != lock["sha256"]:
        parser.error("Local contract and lock disagree")
    try:
        result = inspect_site(args.url, sha, args.expected_commit)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PUBLIC_READ_ONLY_CANDIDATE_SMOKE_PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
