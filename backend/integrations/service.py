"""Data Integrations Service (Workflow 6): Bounded uploads, signed artifact downloads, Notion/Drive/Git sync, and Knowledge search."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
import threading
import time
import uuid
from typing import Any

import queries as Q

HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9._\-]+$")
ALLOWED_UPLOAD_MIMES = {
    "text/plain",
    "text/markdown",
    "application/json",
    "application/pdf",
    "application/zip",
    "image/png",
    "image/jpeg",
}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB


@dataclass
class UploadTicketRec:
    ticket_id: str
    owner_sub: str
    file_name: str
    mime_type: str
    byte_size: int
    expected_sha256: str
    task_id: str | None
    expires_at: float
    state: str = "ISSUED"
    artifact_id: str | None = None

    @property
    def expires_at_iso(self) -> str:
        return datetime.fromtimestamp(self.expires_at, timezone.utc).isoformat()


@dataclass
class DownloadTicketRec:
    ticket_id: str
    artifact_id: str
    owner_sub: str
    expires_at: float

    @property
    def expires_at_iso(self) -> str:
        return datetime.fromtimestamp(self.expires_at, timezone.utc).isoformat()


class IntegrationsService:
    """Implements safe uploads, signed artifact delivery, Notion/Drive/Git metadata sync, and Knowledge Query."""

    def __init__(self, *, engine, store, clock=time.time) -> None:
        self._lock = threading.RLock()
        self.engine = engine
        self.store = store
        self.clock = clock
        self.upload_tickets: dict[str, UploadTicketRec] = {}
        self.download_tickets: dict[str, DownloadTicketRec] = {}
        self.artifact_mimes: dict[str, tuple[str, str]] = {}
        self.knowledge_entries: list[dict[str, Any]] = [
            {
                "id": "kb.magicworkshop-audit",
                "title": "全系统审计包 2026-11-08",
                "source_system": "drive",
                "snippet": "四节点拓扑（美国服务器、Mac mini、UCloud、腾讯云）只读基线审计与 SHA-256 证据包。",
                "uri": "https://drive.google.com/file/d/1pNUDglq9WpzqNowt7M9pWeGIKWt2l7ai/view",
                "kind": "mock",
            },
            {
                "id": "kb.notion-v2-parallel-decision",
                "title": "MagicWorkshop V2 全模块同步开发与一次完整交付决策",
                "source_system": "notion",
                "snippet": "取消 P0-P3 分阶段开发优先级，改为七条工作流同步推进、单一架构契约锁定与集成验收总控。",
                "uri": "https://app.notion.com/p/412fda3814fa81ad9c19e67552d3bc8f",
                "kind": "mock",
            },
            {
                "id": "kb.git-unified-repo",
                "title": "MagicWorkshop 统一仓库 v0.1_personal 契约与源码基线",
                "source_system": "git",
                "snippet": "根目录 contracts/openapi.yaml 唯一活动契约，前后端与 BFF 共享同一 Schema 锁。",
                "uri": "https://github.com/limewuzz/person_ass/tree/v0.1_personal",
                "kind": "mock",
            },
        ]

    def create_upload_ticket(self, body: dict, *, principal) -> dict:
        fname = body["file_name"]
        if "/" in fname or "\\" in fname or ".." in fname or not SAFE_FILENAME_RE.fullmatch(fname):
            raise ValueError("unsafe_file_name")
        mime = body["mime_type"]
        if mime not in ALLOWED_UPLOAD_MIMES:
            raise ValueError("disallowed_mime_type")
        size = int(body["byte_size"])
        if not (1 <= size <= MAX_UPLOAD_BYTES):
            raise ValueError("invalid_byte_size")
        sha = body["sha256"]
        if not HEX64_RE.fullmatch(sha):
            raise ValueError("invalid_sha256")
        task_id = body.get("task_id")
        if task_id:
            task = self.engine.tasks.get(task_id)
            if task is None:
                raise KeyError(task_id)
            if principal.role != "admin" and task.principal_id != principal.sub:
                raise PermissionError("task_forbidden")
        with self._lock:
            tid = str(uuid.uuid4())
            rec = UploadTicketRec(
                ticket_id=tid,
                owner_sub=principal.sub,
                file_name=fname,
                mime_type=mime,
                byte_size=size,
                expected_sha256=sha.lower(),
                task_id=task_id,
                expires_at=self.clock() + 600,
            )
            self.upload_tickets[tid] = rec
            self.engine.audit(principal.sub, "integrations.upload.ticket", tid, f"file={fname}")
            return self.upload_ticket_out(rec)

    def complete_upload(self, ticket_id: str, body: dict, *, principal) -> dict:
        with self._lock, self.engine._lock:
            rec = self.upload_tickets.get(ticket_id)
            if rec is None:
                raise KeyError(ticket_id)
            if principal.role != "admin" and rec.owner_sub != principal.sub:
                raise PermissionError("upload_ticket_forbidden")
            if self.clock() >= rec.expires_at:
                rec.state = "EXPIRED"
                raise ValueError("upload_ticket_expired")
            if rec.state == "COMPLETED" and rec.artifact_id:
                return self.engine.artifacts[rec.artifact_id]
            try:
                raw = base64.b64decode(body["content_base64"], validate=True)
            except Exception as e:
                raise ValueError("invalid_base64_content") from e
            if len(raw) != rec.byte_size:
                raise ValueError("byte_size_mismatch")
            actual_sha = hashlib.sha256(raw).hexdigest()
            if actual_sha != rec.expected_sha256:
                raise ValueError("sha256_mismatch")

            art_id = str(uuid.uuid4())
            bound_task_id = rec.task_id
            if not bound_task_id:
                t, _ = self.engine.create_task(
                    principal_id=principal.sub,
                    capability="local.simulate",
                    capability_version=1,
                    resource_id="local-ledger",
                    idempotency_key=f"upload-task-{ticket_id}",
                    arguments={"outcome": "SUCCEEDED"},
                    origin_channel="web",
                    requires_approval=False,
                    risk="READ",
                    dry_run=True,
                )
                bound_task_id = t.id

            self.engine.artifact_bytes[art_id] = raw
            art_meta = {
                "id": art_id,
                "task_id": bound_task_id,
                "storage_system": "LOCAL_UPLOAD_VAULT",
                "uri": f"memory://uploads/{art_id}/{rec.file_name}",
                "sha256": actual_sha,
                "byte_size": len(raw),
            }
            self.engine.artifacts[art_id] = art_meta
            self.artifact_mimes[art_id] = (rec.file_name, rec.mime_type)
            rec.state = "COMPLETED"
            rec.artifact_id = art_id
            self.engine.audit(principal.sub, "integrations.upload.complete", art_id, f"sha256={actual_sha[:12]}")
            return art_meta

    def upload_ticket_out(self, rec: UploadTicketRec) -> dict:
        return {
            "ticket_id": rec.ticket_id,
            "upload_url": f"/api/v1/uploads/{rec.ticket_id}",
            "expires_at": rec.expires_at_iso,
            "max_bytes": rec.byte_size,
            "expected_sha256": rec.expected_sha256,
            "state": rec.state,
            "artifact_id": rec.artifact_id,
        }

    def _verify_artifact_access(self, art_id: str, principal) -> dict:
        art = self.engine.artifacts.get(art_id)
        if art is None:
            raise KeyError(art_id)
        uri = art.get("uri", "")
        if uri.startswith(("http://", "https://", "file://")):
            raise PermissionError("external_or_local_file_uri_proxy_forbidden")
        task = self.engine.tasks.get(art["task_id"])
        if task is not None and principal.role not in {"admin", "approver"} and task.principal_id != principal.sub:
            raise PermissionError("artifact_forbidden")
        return art

    def create_download_ticket(self, art_id: str, *, principal) -> dict:
        with self._lock:
            art = self._verify_artifact_access(art_id, principal)
            raw = self.engine.artifact_bytes.get(art_id)
            if raw is None:
                raise KeyError(art_id)
            fname, _ = self.artifact_mimes.get(art_id, (f"{art_id}.json", "application/json"))
            tid = str(uuid.uuid4())
            rec = DownloadTicketRec(
                ticket_id=tid,
                artifact_id=art_id,
                owner_sub=principal.sub,
                expires_at=self.clock() + 300,
            )
            self.download_tickets[tid] = rec
            self.engine.audit(principal.sub, "integrations.artifact.download_ticket", art_id, f"ticket={tid}")
            return {
                "ticket_id": tid,
                "artifact_id": art_id,
                "download_url": f"/api/v1/artifacts/{art_id}/content?ticket={tid}",
                "expires_at": rec.expires_at_iso,
                "sha256": art["sha256"],
                "byte_size": art["byte_size"],
                "disposition": f'attachment; filename="{fname}"',
            }

    def get_artifact_content(self, art_id: str, *, ticket_id: str | None, principal) -> dict:
        with self._lock:
            art = self._verify_artifact_access(art_id, principal)
            if ticket_id:
                trec = self.download_tickets.get(ticket_id)
                if trec is None or trec.artifact_id != art_id or self.clock() >= trec.expires_at:
                    raise PermissionError("invalid_or_expired_download_ticket")
            raw = self.engine.artifact_bytes.get(art_id)
            if raw is None:
                raise KeyError(art_id)
            actual_sha = hashlib.sha256(raw).hexdigest()
            if actual_sha != art["sha256"]:
                raise ValueError("artifact_checksum_mismatch")
            fname, mime = self.artifact_mimes.get(art_id, (f"{art_id}.json", "application/json"))
            self.engine.audit(principal.sub, "integrations.artifact.download", art_id, "ok")
            return {
                "artifact_id": art_id,
                "sha256": actual_sha,
                "byte_size": len(raw),
                "mime_type": mime,
                "disposition": f'attachment; filename="{fname}"',
                "content_base64": base64.b64encode(raw).decode("ascii"),
            }

    def sync_integration(self, int_id: str, body: dict, *, principal) -> dict:
        if "cherry" in int_id.lower():
            raise PermissionError("cherry_frozen_boundary")
        if body.get("dry_run") is not True:
            raise ValueError("dry_run_required")
        known_ids = {"int.google-drive", "int.notion", "int.git", "int.rakazo"}
        if int_id not in known_ids:
            raise KeyError(int_id)
        sync_id = str(uuid.uuid4())
        self.engine.audit(principal.sub, "integrations.sync", int_id, f"sync_id={sync_id}")
        return {
            "integration_id": int_id,
            "sync_id": sync_id,
            "status": "SIMULATED_OK",
            "authority_preserved": True,
            "synced_at": Q._now(),
            "source_meta": Q._meta("mock"),
        }

    def query_knowledge(self, body: dict, *, principal) -> dict:
        q = body["query"].strip().lower()
        sources = set(body.get("sources") or [])
        limit = int(body.get("limit") or 10)
        matched = []
        for entry in self.knowledge_entries:
            if sources and entry["source_system"] not in sources:
                continue
            if (
                q in entry["title"].lower()
                or q in entry["snippet"].lower()
                or q in entry["source_system"].lower()
                or q == "*"
            ):
                matched.append(
                    {
                        "id": entry["id"],
                        "title": entry["title"],
                        "source_system": entry["source_system"],
                        "snippet": entry["snippet"],
                        "uri": entry["uri"],
                        "source_meta": Q._meta(entry["kind"]),
                    }
                )
        self.engine.audit(principal.sub, "integrations.knowledge.query", q[:40], f"hits={len(matched[:limit])}")
        return {
            "query": body["query"],
            "items": matched[:limit],
            "source_meta": Q._meta("mock"),
        }
