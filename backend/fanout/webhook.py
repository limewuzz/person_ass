"""HMAC preflight outside the PG transaction; bounded body, deadline and scoped keys."""

import hashlib, hmac, json, os, re, time, stat
from pathlib import Path
import anyio
from starlette.datastructures import Headers
from contract_wire import error_response


class WebhookAuth:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/api/v1/webhooks/trigger":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        raw = bytearray()
        try:
            with anyio.fail_after(5):
                while True:
                    msg = await receive()
                    if msg["type"] == "http.disconnect":
                        return
                    raw.extend(msg.get("body", b""))
                    if len(raw) > 65536:
                        return await error_response(400, "webhook_body_too_large")(
                            scope, receive, send
                        )
                    if not msg.get("more_body"):
                        break
            config = json.loads(Path(os.environ["MWCP_WEBHOOK_KEYS_FILE"]).read_text())
            kid = headers.get("X-MW-Key-Id", "")
            grant = config["keys"].get(kid)
            if not grant or (
                "expires_at" in grant and time.time() >= grant["expires_at"]
            ):
                raise ValueError()
            fd = os.open(
                grant["secret_file"], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            )
            try:
                info = os.fstat(fd)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_mode & 0o077
                    or info.st_size > 4096
                ):
                    raise ValueError()
                secret = os.read(fd, 4097).strip()
            finally:
                os.close(fd)
            if (
                not isinstance(grant.get("owner_sub"), str)
                or not grant["owner_sub"]
                or not isinstance(grant.get("recipes"), list)
            ):
                raise ValueError()
            if len(secret) < 32:
                raise ValueError()
            ts = headers.get("X-MW-Timestamp", "")
            nonce = headers.get("X-MW-Nonce", "")
            key = headers.get("Idempotency-Key", "")
            if (
                abs(time.time() - int(ts)) > 300
                or not re.fullmatch(r"[A-Za-z0-9_-]{12,128}", nonce)
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{12,256}", key)
            ):
                raise ValueError()
            canonical = (
                f"{ts}\n{nonce}\n{key}\n{hashlib.sha256(raw).hexdigest()}".encode()
            )
            signature = headers.get("X-MW-Signature", "")
            if not signature.isascii() or not hmac.compare_digest(
                hmac.new(secret, canonical, hashlib.sha256).hexdigest(), signature
            ):
                raise ValueError()
            scope.setdefault("state", {})["webhook_grant"] = {
                k: v for k, v in grant.items() if k != "secret_file"
            }
            scope["state"]["webhook_nonce"] = (
                kid,
                nonce,
                hashlib.sha256(canonical).hexdigest(),
            )
        except (KeyError, OSError):
            return await error_response(503, "webhook_not_configured")(
                scope, receive, send
            )
        except (ValueError, TypeError, AttributeError, TimeoutError):
            return await error_response(401, "webhook_signature_rejected")(
                scope, receive, send
            )
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(raw), "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)
