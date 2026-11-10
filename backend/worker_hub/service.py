"""Worker Hub & Compute Service (Workflow 4): Server node registration (V2-EXT-003), pairing, worker progress, and Compute Runs."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import re
import secrets
import threading
import time
import uuid
from typing import Any

import queries as Q
from registry import NodeRec, RegistryService, ResourceRec, NODE_ROLES
from taskengine import TaskEngineError, _now_iso, json_stable

HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
PAIRING_TTL_SECONDS = 300


@dataclass
class PairingTicketRec:
    pairing_id: str
    pairing_code: str
    device_name: str
    platform: str
    requested_capabilities: list[str]
    node_id: str | None
    state: str
    expires_at: float
    issued_worker_id: str | None = None

    @property
    def expires_at_iso(self) -> str:
        return datetime.fromtimestamp(self.expires_at, timezone.utc).isoformat()


@dataclass
class ComputeRunRec:
    id: str
    title: str
    runtime_kind: str
    git_commit: str
    dataset_sha256: str
    execution_id: str
    state: str
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    last_checkpoint_artifact_id: str | None = None
    source_kind: str = "mock"


class WorkerHubService:
    """Manages server node registration, device pairing, worker progress, and Compute Runs with checkpoint recovery."""

    def __init__(self, *, store, engine, gateway, clock=time.time) -> None:
        self._lock = threading.RLock()
        self.store = store
        self.engine = engine
        self.gateway = gateway
        self.clock = clock
        self.node_certs: dict[str, str] = {}
        self.pairings: dict[str, PairingTicketRec] = {}
        self.compute_runs: dict[str, ComputeRunRec] = {}
        self._seed_baseline_runs()

    def _seed_baseline_runs(self) -> None:
        r = ComputeRunRec(
            id="run.baseline-emer-coarse",
            title="EMER-Coarse Audio Baseline PoC",
            runtime_kind="colab_ephemeral",
            git_commit="ae654d41712e07d68a4b424f031a694eb27537a7",
            dataset_sha256="b" * 64,
            execution_id="exec-colab-001",
            state="PREPARED",
            source_kind="unavailable",
        )
        self.compute_runs[r.id] = r

    def register_node(self, body: dict, *, actor: str) -> dict:
        nid = body["id"]
        role = body["role"]
        cert_fp = body["cert_fingerprint_sha256"]
        if role not in NODE_ROLES:
            raise ValueError("invalid_node_role")
        if not HEX64_RE.fullmatch(cert_fp):
            raise ValueError("invalid_cert_fingerprint")
        if "cherry" in nid.lower() or "cherry" in body["owner_system"].lower():
            raise PermissionError("cherry_frozen_boundary")

        svc = RegistryService(self.store)
        with self._lock, self.store._target_lock:
            existing_res = self.store.resources.get(f"node.{nid}")
            expected_gen = body.get("expected_generation")
            if existing_res is not None:
                if expected_gen is None or existing_res.generation != int(expected_gen):
                    raise FileExistsError("node_registration_generation_conflict")
                svc.transfer_owner(
                    f"node.{nid}",
                    body["owner_system"],
                    expected_generation=int(expected_gen),
                )
            else:
                svc.register(
                    ResourceRec(
                        f"node.{nid}",
                        "node",
                        body["owner_system"],
                        body["name"],
                        nid,
                        source="v2-node-registry",
                    )
                )
            node_rec = NodeRec(
                id=nid,
                name=body["name"],
                role=role,
                source="v2-node-registry",
                observed_at=_now_iso(),
                received_at=_now_iso(),
                ttl_seconds=3600,
                base_health="unknown",
            )
            self.store.nodes[nid] = node_rec
            self.node_certs[nid] = cert_fp.lower()
            self.engine.audit(actor, "worker_hub.node.register", nid, f"role={role}")
            return self.store.node_out(node_rec)

    def revoke_node(self, nid: str, *, actor: str) -> dict:
        svc = RegistryService(self.store)
        with self._lock, self.store._target_lock:
            node_rec = self.store.nodes.get(nid)
            if node_rec is None:
                raise KeyError(nid)
            node_rec.base_health = "offline"
            out = self.store.node_out(node_rec)
            if nid not in {"us-server", "mac-mini", "ucloud-vps", "tencent-cloud"}:
                self.store.nodes.pop(nid, None)
            res_id = f"node.{nid}"
            if res_id in self.store.resources and self.store.resources[res_id].lifecycle_state == "ACTIVE":
                svc.delete(res_id)
            self.engine.audit(actor, "worker_hub.node.revoke", nid, "offline_revoked")
            return out

    def init_pairing(self, body: dict, *, actor: str) -> dict:
        caps = list(body.get("requested_capabilities") or [])
        with self._lock, self.store._target_lock:
            for c in caps:
                cap_rec = self.store.capabilities.get(c) or self.store.capabilities.get((c, 1))
                if cap_rec is None:
                    raise ValueError(f"capability_not_in_allowlist:{c}")
                if cap_rec.risk in {"HIGH", "CRITICAL"}:
                    raise PermissionError(f"high_risk_capability_forbidden:{c}")
            pid = str(uuid.uuid4())
            code = f"{secrets.randbelow(900000) + 100000}"
            rec = PairingTicketRec(
                pairing_id=pid,
                pairing_code=code,
                device_name=body["device_name"],
                platform=body["platform"],
                requested_capabilities=caps,
                node_id=body.get("node_id") or "mac-mini",
                state="PENDING",
                expires_at=self.clock() + PAIRING_TTL_SECONDS,
            )
            self.pairings[pid] = rec
            self.engine.audit(actor, "worker_hub.device.pair_init", pid, f"platform={rec.platform}")
            return self.pairing_out(rec)

    def confirm_pairing(self, body: dict, *, actor: str) -> dict:
        pid = body["pairing_id"]
        code = body["pairing_code"]
        with self._lock:
            rec = self.pairings.get(pid)
            if rec is None:
                raise KeyError(pid)
            if self.clock() >= rec.expires_at:
                rec.state = "EXPIRED"
                raise ValueError("pairing_expired")
            if rec.state != "PENDING":
                raise FileExistsError("pairing_already_consumed")
            if not secrets.compare_digest(rec.pairing_code, code):
                raise PermissionError("invalid_pairing_code")
            rec.state = "CONFIRMED"
            worker_id = f"worker.{rec.platform}.{pid[:8]}"
            rec.issued_worker_id = worker_id
            self.gateway.heartbeat(
                worker_id,
                node_id=rec.node_id or "mac-mini",
                version="v2.0.0",
                available_capabilities=rec.requested_capabilities,
            )
            self.engine.audit(actor, "worker_hub.device.pair_confirm", worker_id, "confirmed")
            return self.pairing_out(rec)

    def pairing_out(self, rec: PairingTicketRec) -> dict:
        return {
            "pairing_id": rec.pairing_id,
            "pairing_code": rec.pairing_code,
            "state": rec.state,
            "expires_at": rec.expires_at_iso,
            "platform": rec.platform,
            "issued_worker_id": rec.issued_worker_id,
        }

    def report_progress(
        self,
        worker_id: str,
        task_id: str,
        *,
        generation: int,
        lease_token: str,
        progress_percent: int,
        summary: str,
    ) -> dict:
        with self.gateway._domain_lock():
            lease = self.gateway._lease_for(worker_id, task_id, generation, lease_token)
            task = self.engine._require(task_id)
            if task.state not in {"LEASED", "RUNNING"}:
                raise TaskEngineError("illegal_transition", "task not leased or running", 409)
            if task.state == "LEASED":
                self.engine.transition(
                    task_id,
                    "RUNNING",
                    actor=worker_id,
                    summary=f"started via progress ({progress_percent}%)",
                )
                lease.started = True
            self.engine._emit(task, "progress", f"[{progress_percent}%] {summary}")
            self.engine.audit(worker_id, "worker.progress", task_id, f"{progress_percent}%")
            return {
                "status": "ok",
                "checked_at": _now_iso(),
                "component": "worker-gateway",
            }

    def create_compute_run(self, body: dict, *, actor: str) -> dict:
        if body.get("dry_run") is not True:
            raise ValueError("dry_run_required")
        if not HEX64_RE.fullmatch(body["dataset_sha256"]):
            raise ValueError("invalid_dataset_sha256")
        with self._lock:
            rid = f"run.{uuid.uuid4().hex[:12]}"
            rec = ComputeRunRec(
                id=rid,
                title=body["title"],
                runtime_kind=body["runtime_kind"],
                git_commit=body["git_commit"],
                dataset_sha256=body["dataset_sha256"].lower(),
                execution_id=f"exec-{uuid.uuid4().hex[:10]}",
                state="PREPARED",
                source_kind="mock",
            )
            self.compute_runs[rid] = rec
            self.engine.audit(actor, "worker_hub.compute_run.create", rid, f"exec={rec.execution_id}")
            return self.compute_run_out(rec)

    def get_compute_run(self, rid: str) -> dict:
        with self._lock:
            rec = self.compute_runs.get(rid)
            if rec is None:
                raise KeyError(rid)
            return self.compute_run_out(rec)

    def record_checkpoint(self, rid: str, body: dict, *, actor: str) -> dict:
        if not HEX64_RE.fullmatch(body["artifact_sha256"]):
            raise ValueError("invalid_artifact_sha256")
        with self._lock, self.engine._lock:
            rec = self.compute_runs.get(rid)
            if rec is None:
                raise KeyError(rid)
            art_id = str(uuid.uuid4())
            ckpt_payload = {
                "run_id": rid,
                "execution_id": rec.execution_id,
                "step": body["step"],
                "sha256": body["artifact_sha256"].lower(),
                "metrics": body.get("metrics") or {},
            }
            raw_bytes = json_stable(ckpt_payload).encode("utf-8")
            self.engine.artifact_bytes[art_id] = raw_bytes
            self.engine.artifacts[art_id] = {
                "id": art_id,
                "task_id": rid,
                "storage_system": "DRIVE_CHECKPOINT_MOCK",
                "uri": f"gdrive://checkpoint/{rid}/step-{body['step']}.ckpt",
                "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "byte_size": int(body["byte_size"]),
            }
            rec.checkpoints.append(
                {
                    "step": int(body["step"]),
                    "artifact_id": art_id,
                    "artifact_sha256": body["artifact_sha256"].lower(),
                    "recorded_at": _now_iso(),
                }
            )
            rec.last_checkpoint_artifact_id = art_id
            rec.state = "CHECKPOINTED"
            self.engine.audit(actor, "worker_hub.compute_run.checkpoint", rid, f"step={body['step']}")
            return self.compute_run_out(rec)

    def compute_run_out(self, rec: ComputeRunRec) -> dict:
        return {
            "id": rec.id,
            "title": rec.title,
            "runtime_kind": rec.runtime_kind,
            "git_commit": rec.git_commit,
            "dataset_sha256": rec.dataset_sha256,
            "execution_id": rec.execution_id,
            "state": rec.state,
            "checkpoints": list(rec.checkpoints),
            "last_checkpoint_artifact_id": rec.last_checkpoint_artifact_id,
            "source_meta": Q._meta(rec.source_kind),
        }
