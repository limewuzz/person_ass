"""Server-side HttpOnly/Secure/SameSite session & CSRF manager for MagicWorkshop V2."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import secrets
import threading
import time
from typing import Callable

from auth import Principal
from contract_wire import identity

SESSION_TTL_SECONDS = 3600


@dataclass
class SessionRec:
    session_id: str
    csrf_token: str
    principal: Principal
    client_platform: str
    device_id: str | None
    created_at: float
    expires_at: float
    revoked: bool = False

    @property
    def expires_at_iso(self) -> str:
        return datetime.fromtimestamp(self.expires_at, timezone.utc).isoformat()


class SessionManager:
    """Thread-safe server-side session store supporting HttpOnly cookie + CSRF token validation."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._lock = threading.RLock()
        self.clock = clock
        self.sessions: dict[str, SessionRec] = {}

    def create_session(
        self,
        principal: Principal,
        *,
        client_platform: str = "web",
        device_id: str | None = None,
        ttl_seconds: int = SESSION_TTL_SECONDS,
    ) -> SessionRec:
        now = self.clock()
        rec = SessionRec(
            session_id=secrets.token_urlsafe(24),
            csrf_token=secrets.token_urlsafe(24),
            principal=principal,
            client_platform=client_platform,
            device_id=device_id,
            created_at=now,
            expires_at=now + ttl_seconds,
        )
        with self._lock:
            self.sessions[rec.session_id] = rec
        return rec

    def get_valid_session(self, session_id: str) -> SessionRec | None:
        with self._lock:
            rec = self.sessions.get(session_id)
            if rec is None or rec.revoked or self.clock() >= rec.expires_at:
                return None
            return rec

    def revoke_session(self, session_id: str) -> bool:
        with self._lock:
            rec = self.sessions.get(session_id)
            if rec is None:
                return False
            rec.revoked = True
            return True

    def revoke_by_device(self, owner_sub: str, device_id: str) -> int:
        count = 0
        with self._lock:
            for rec in self.sessions.values():
                if rec.principal.sub == owner_sub and rec.device_id == device_id and not rec.revoked:
                    rec.revoked = True
                    count += 1
        return count

    def session_out(self, rec: SessionRec) -> dict:
        p = rec.principal
        return {
            "session_id": rec.session_id,
            "csrf_token": rec.csrf_token,
            "expires_at": rec.expires_at_iso,
            "principal": identity(p),
            "cookie_flags": {
                "http_only": True,
                "secure": True,
                "same_site": "Strict",
            },
        }
