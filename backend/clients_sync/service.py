"""Multi-Platform Client Sync Service (Workflow 5): Device registration (V2-EXT-004), remote wipe, state CAS sync, and releases."""
from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Any

import queries as Q

PLATFORM_KEYSTORE_MAP = {
    "android": "android_keystore",
    "macos": "macos_keychain",
    "windows": "windows_credential_manager",
    "web": "web_httponly_cookie",
}


@dataclass
class ClientDeviceRec:
    device_id: str
    owner_sub: str
    platform: str
    app_version: str
    os_arch: str
    keystore_kind: str
    wipe_pending: bool = False
    revoked: bool = False
    updated_at: str = ""


@dataclass
class ClientSyncRec:
    owner_sub: str
    revision: int = 0
    cursor: str = "sync-cursor-0"
    draft_work_items: list[dict[str, Any]] = field(default_factory=list)
    ui_preferences: dict[str, Any] = field(default_factory=lambda: {"theme": "system", "locale": "zh-CN"})
    updated_at: str = ""


class ClientSyncService:
    """Manages cross-platform devices (Android/macOS/Windows/Web), remote wipe, and revision-checked state sync."""

    def __init__(self, *, engine, session_mgr) -> None:
        self._lock = threading.RLock()
        self.engine = engine
        self.session_mgr = session_mgr
        self.devices: dict[str, ClientDeviceRec] = {}
        self.sync_states: dict[str, ClientSyncRec] = {}

    def register_device(self, body: dict, *, owner_sub: str) -> dict:
        platform = body["platform"]
        keystore = body["keystore_kind"]
        expected_keystore = PLATFORM_KEYSTORE_MAP.get(platform)
        if expected_keystore and keystore != expected_keystore:
            raise ValueError(f"keystore_mismatch_for_{platform}")
        did = body["device_id"]
        now = Q._now()
        with self._lock:
            existing = self.devices.get(did)
            if existing and existing.owner_sub != owner_sub:
                raise PermissionError("device_owned_by_another_principal")
            rec = ClientDeviceRec(
                device_id=did,
                owner_sub=owner_sub,
                platform=platform,
                app_version=body["app_version"],
                os_arch=body["os_arch"],
                keystore_kind=keystore,
                wipe_pending=False,
                revoked=False,
                updated_at=now,
            )
            self.devices[did] = rec
            self.engine.audit(owner_sub, "clients.device.register", did, f"platform={platform}")
            return self.device_out(rec)

    def list_devices(self, *, principal) -> list[dict]:
        with self._lock:
            return [
                self.device_out(d)
                for d in self.devices.values()
                if principal.role == "admin" or d.owner_sub == principal.sub
            ]

    def wipe_device(self, did: str, *, principal) -> dict:
        with self._lock:
            rec = self.devices.get(did)
            if rec is None:
                raise KeyError(did)
            if principal.role != "admin" and rec.owner_sub != principal.sub:
                raise PermissionError("device_forbidden")
            rec.wipe_pending = True
            rec.revoked = True
            rec.updated_at = Q._now()
            self.session_mgr.revoke_by_device(rec.owner_sub, did)
            self.engine.audit(principal.sub, "clients.device.wipe", did, "remote_wipe_and_revoke")
            return self.device_out(rec)

    def get_sync_state(self, *, owner_sub: str) -> dict:
        with self._lock:
            state = self.sync_states.get(owner_sub)
            if state is None:
                state = ClientSyncRec(owner_sub=owner_sub, updated_at=Q._now())
                self.sync_states[owner_sub] = state
            return self.sync_out(state)

    def update_sync_state(self, body: dict, *, owner_sub: str) -> dict:
        did = body["device_id"]
        expected_rev = int(body["expected_revision"])
        with self._lock:
            dev = self.devices.get(did)
            if dev and dev.revoked:
                raise PermissionError("device_revoked_wipe_required")
            state = self.sync_states.get(owner_sub)
            if state is None:
                state = ClientSyncRec(owner_sub=owner_sub, revision=0, updated_at=Q._now())
                self.sync_states[owner_sub] = state
            if state.revision != expected_rev:
                raise FileExistsError("sync_conflict")
            state.revision += 1
            state.cursor = f"sync-cursor-{state.revision}"
            state.draft_work_items = list(body.get("draft_work_items") or [])
            state.ui_preferences = dict(body.get("ui_preferences") or {})
            state.updated_at = Q._now()
            self.engine.audit(owner_sub, "clients.sync.commit", did, f"rev={state.revision}")
            return self.sync_out(state)

    def get_release_manifest(self) -> dict:
        return {
            "contract_version": "2.0.0-unified-v2",
            "min_compatible_contract": "1.1.1-local-integrated",
            "platforms": {
                "web": {
                    "version": "2.0.0-rc1",
                    "bundle_sha256": None,
                    "signed": False,
                    "status": "PENDING_VERIFIED_BUILD",
                },
                "android": {
                    "version": "2.0.0-draft",
                    "min_sdk": 31,
                    "target_sdk": 35,
                    "apk_sha256": None,
                    "signed": False,
                    "status": "SPECIFIED_PENDING_BUILD",
                },
                "macos": {
                    "version": "2.0.0-draft",
                    "arch": ["arm64", "x64"],
                    "dmg_sha256": None,
                    "notarized": False,
                    "status": "SPECIFIED_PENDING_BUILD",
                },
                "windows": {
                    "version": "2.0.0-draft",
                    "arch": ["x64", "arm64"],
                    "installer_sha256": None,
                    "authenticode_signed": False,
                    "status": "SPECIFIED_PENDING_BUILD",
                },
            },
            "source_meta": Q._meta("mock"),
        }

    def device_out(self, rec: ClientDeviceRec) -> dict:
        return {
            "device_id": rec.device_id,
            "owner_sub": rec.owner_sub,
            "platform": rec.platform,
            "app_version": rec.app_version,
            "os_arch": rec.os_arch,
            "keystore_kind": rec.keystore_kind,
            "wipe_pending": rec.wipe_pending,
            "revoked": rec.revoked,
            "updated_at": rec.updated_at,
        }

    def sync_out(self, rec: ClientSyncRec) -> dict:
        return {
            "owner_sub": rec.owner_sub,
            "revision": rec.revision,
            "cursor": rec.cursor,
            "draft_work_items": list(rec.draft_work_items),
            "ui_preferences": dict(rec.ui_preferences),
            "updated_at": rec.updated_at,
        }
