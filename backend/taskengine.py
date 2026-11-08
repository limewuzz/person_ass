"""Task Engine（本地 RC）：WorkItems / Tasks 状态机 / 幂等 / 事件 / 尝试 / 审计总线。

契约：contracts/openapi.yaml 1.1（41/43）+ database/001_control_plane.sql 状态枚举。
持久化：内存实现（repository 协议见 dbpg/repository.py；PG 侧 NOT RUN）。
"""
from __future__ import annotations

import hashlib
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

TASK_STATES = {
    "DRAFT", "VALIDATING", "WAITING_APPROVAL", "QUEUED", "LEASED", "RUNNING",
    "SUCCEEDED", "FAILED", "CANCELED", "EXPIRED", "NEEDS_RECONCILIATION",
}
TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELED", "EXPIRED"}
# 状态机合法跳转（SQL 语义 + worker/approval 流）
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"VALIDATING", "WAITING_APPROVAL", "QUEUED", "CANCELED"},
    "VALIDATING": {"WAITING_APPROVAL", "QUEUED", "FAILED", "CANCELED"},
    "WAITING_APPROVAL": {"QUEUED", "CANCELED", "EXPIRED"},
    "QUEUED": {"LEASED", "CANCELED", "EXPIRED", "NEEDS_RECONCILIATION"},
    "LEASED": {"RUNNING", "QUEUED", "EXPIRED", "NEEDS_RECONCILIATION", "CANCELED"},
    "RUNNING": {"SUCCEEDED", "FAILED", "EXPIRED", "NEEDS_RECONCILIATION"},
    "NEEDS_RECONCILIATION": {"QUEUED", "SUCCEEDED", "FAILED", "CANCELED", "EXPIRED"},
    "SUCCEEDED": set(), "FAILED": set(), "CANCELED": set(), "EXPIRED": set(),
}
WORK_ITEM_KINDS = {"task", "idea", "paper", "issue", "project"}
WORK_ITEM_STATUSES = {"open", "in_progress", "blocked", "done", "archived"}
OUTCOMES = {"SUCCEEDED", "FAILED", "CANCELED", "EXPIRED"}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def _payload_hash(arguments: dict) -> str:
    return hashlib.sha256(
        json_stable(arguments).encode("utf-8")).hexdigest()


def json_stable(obj: Any) -> str:
    import json
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class TaskEngineError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(f"{code}: {message}")  # str 含 code（测试/日志可按 code 匹配）
        self.code = code
        self.status = status if isinstance(status, int) else 400


@dataclass
class WorkItemRec:
    id: str
    title: str
    kind: str
    status: str = "open"
    created_by: str = ""
    source_system: str | None = None
    source_external_id: str | None = None
    created_at: str = field(default_factory=_now_iso)


@dataclass
class TaskEventRec:
    id: str
    task_id: str
    sequence: int
    kind: str
    occurred_at: str
    summary: str
    trace_id: str


@dataclass
class TaskAttemptRec:
    id: str
    task_id: str
    worker_id: str
    generation: int
    started_at: str | None = None
    finished_at: str | None = None
    outcome: str | None = None
    result_summary: str | None = None  # 脱敏摘要


@dataclass
class TaskRec:
    id: str
    principal_id: str            # 创建者（幂等键一部分）
    capability: str
    capability_version: int
    resource_id: str
    idempotency_key: str
    request_hash: str
    args_redacted: dict = field(default_factory=dict)
    origin_channel: str = "web"
    origin_external_ref: str | None = None
    work_item_id: str | None = None
    state: str = "DRAFT"
    generation: int = 0          # 分配/重试代数（与 worker lease 联动）
    priority: int = 0
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    requires_approval: bool = False
    risk: str = "READ"
    dry_run: bool = False


class TaskEngine:
    """统一锁保护的任务引擎（与 RegistryService 同一并发纪律）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.work_items: dict[str, WorkItemRec] = {}
        self._wi_dedup: dict[tuple, str] = {}       # (source_system, source_external_id) -> id
        self.tasks: dict[str, TaskRec] = {}
        self.events: dict[str, list[TaskEventRec]] = {}
        self.attempts: dict[str, list[TaskAttemptRec]] = {}
        self._idem: dict[tuple, str] = {}           # (principal, scope, key, hash) -> task_id
        self._seq: dict[str, int] = {}              # task -> event sequence
        self.audit_bus: list[dict] = []             # 审计事件（SSE/history 源）
        self._audit_seq = 0

    # ---------- 审计 ----------
    def audit(self, actor_ref: str, action: str, resource_ref: str, result: str,
              trace_id: str = "") -> dict:
        with self._lock:
            self._audit_seq += 1
            ev = {"id": f"ae-{self._audit_seq}", "actor_ref": actor_ref, "action": action,
                  "resource_ref": resource_ref, "result": result,
                  "created_at": _now_iso(), "trace_id": trace_id}
            self.audit_bus.append(ev)
            return ev

    def _emit(self, task: TaskRec, kind: str, summary: str) -> None:
        self._seq[task.id] = self._seq.get(task.id, 0) + 1
        self.events.setdefault(task.id, []).append(TaskEventRec(
            id=f"te-{task.id}-{self._seq[task.id]}", task_id=task.id,
            sequence=self._seq[task.id], kind=kind, occurred_at=_now_iso(),
            summary=summary, trace_id=task.trace_id))

    # ---------- WorkItems ----------
    def create_work_item(self, *, title: str, kind: str, created_by: str,
                         source_system: str | None = None,
                         source_external_id: str | None = None) -> WorkItemRec:
        if not (1 <= len(title) <= 200):
            raise TaskEngineError("bad_title", "title length 1..200")
        if kind not in WORK_ITEM_KINDS:
            raise TaskEngineError("bad_kind", f"kind must be in {sorted(WORK_ITEM_KINDS)}")
        with self._lock:
            if source_system and source_external_id:
                key = (source_system, source_external_id)
                if key in self._wi_dedup:
                    return self.work_items[self._wi_dedup[key]]  # 幂等
            rec = WorkItemRec(id=f"wi-{uuid.uuid4()}", title=title, kind=kind,
                              created_by=created_by, source_system=source_system,
                              source_external_id=source_external_id)
            self.work_items[rec.id] = rec
            if source_system and source_external_id:
                self._wi_dedup[(source_system, source_external_id)] = rec.id
            self.audit(created_by, "work_item.create", rec.id, "ok")
            return rec

    def work_item_out(self, r: WorkItemRec) -> dict:
        return {"id": r.id, "title": r.title, "kind": r.kind, "status": r.status,
                "created_at": r.created_at, "created_by": r.created_by,
                "source_system": r.source_system}

    # ---------- Tasks ----------
    def create_task(self, *, principal_id: str, capability: str, capability_version: int,
                    resource_id: str, idempotency_key: str, arguments: dict,
                    origin_channel: str = "web", origin_external_ref: str | None = None,
                    work_item_id: str | None = None, requires_approval: bool = False,
                    risk: str = "READ", dry_run: bool = False) -> tuple[TaskRec, bool]:
        """幂等创建：同 (principal, capability-scope, key, payload_hash) 重复请求返回
        既有任务（replayed=True）；payload 不同则 409。100 并发仅建一条。"""
        if not (12 <= len(idempotency_key) <= 256):
            raise TaskEngineError("bad_idempotency_key", "idempotency_key length 12..256")
        if origin_channel not in ("web", "android", "cli", "rakazo", "system", "other"):
            raise TaskEngineError("bad_origin", "bad origin channel")
        ph = _payload_hash(arguments)
        key = (principal_id, f"{capability}@{capability_version}", idempotency_key)
        with self._lock:
            existing_id = self._idem.get(key)
            if existing_id:
                existing = self.tasks[existing_id]
                if existing.request_hash != ph:
                    raise TaskEngineError("idempotency_conflict",
                                          "same idempotency key with different payload", 409)
                return existing, True
            rec = TaskRec(id=f"tk-{uuid.uuid4()}", principal_id=principal_id,
                          capability=capability, capability_version=capability_version,
                          resource_id=resource_id, idempotency_key=idempotency_key,
                          request_hash=ph, args_redacted=_redact_args(arguments),
                          origin_channel=origin_channel,
                          origin_external_ref=origin_external_ref,
                          work_item_id=work_item_id,
                          requires_approval=requires_approval, risk=risk, dry_run=dry_run)
            rec.state = "WAITING_APPROVAL" if requires_approval else "QUEUED"
            self.tasks[rec.id] = rec
            self._idem[key] = rec.id
            self._emit(rec, "created", f"task created in {rec.state}")
            self.audit(principal_id, "task.create", rec.id, "ok", rec.trace_id)
            return rec, False

    def transition(self, task_id: str, new_state: str, *, actor: str = "system",
                   summary: str = "") -> TaskRec:
        with self._lock:
            task = self._require(task_id)
            if new_state not in TASK_STATES:
                raise TaskEngineError("bad_state", f"unknown state {new_state}")
            if new_state not in ALLOWED_TRANSITIONS[task.state]:
                raise TaskEngineError(
                    "illegal_transition",
                    f"illegal transition {task.state}->{new_state}", 409)
            old = task.state
            task.state = new_state
            task.updated_at = _now_iso()
            self._emit(task, "state", summary or f"{old}->{new_state}")
            self.audit(actor, "task.transition", task_id, f"{old}->{new_state}", task.trace_id)
            return task

    def bump_generation(self, task_id: str, *, actor: str = "system") -> int:
        with self._lock:
            task = self._require(task_id)
            task.generation += 1
            task.updated_at = _now_iso()
            return task.generation

    def add_attempt(self, task_id: str, worker_id: str, generation: int) -> TaskAttemptRec:
        with self._lock:
            task = self._require(task_id)
            rec = TaskAttemptRec(id=f"at-{uuid.uuid4()}", task_id=task_id,
                                 worker_id=worker_id, generation=generation)
            self.attempts.setdefault(task_id, []).append(rec)
            self._emit(task, "attempt_started",
                       f"attempt g{generation} by {worker_id}")
            return rec

    def finish_attempt(self, attempt_id: str, *, outcome: str,
                       result_summary: str | None) -> TaskAttemptRec:
        with self._lock:
            for lst in self.attempts.values():
                for a in lst:
                    if a.id == attempt_id:
                        if a.finished_at is not None:
                            raise TaskEngineError("attempt_finished", "attempt already finished", 409)
                        if outcome not in OUTCOMES:
                            raise TaskEngineError("bad_outcome", f"outcome in {sorted(OUTCOMES)}")
                        a.finished_at = _now_iso()
                        a.outcome = outcome
                        a.result_summary = (result_summary or "")[:500]
                        return a
        raise TaskEngineError("attempt_not_found", "attempt not found", 404)

    def task_out(self, r: TaskRec) -> dict:
        return {"id": r.id, "work_item_id": r.work_item_id, "capability": r.capability,
                "capability_version": r.capability_version, "resource_id": r.resource_id,
                "state": r.state, "generation": r.generation, "priority": r.priority,
                "trace_id": r.trace_id, "created_at": r.created_at,
                "updated_at": r.updated_at,
                "origin": {"channel": r.origin_channel, "source_ref": r.origin_external_ref},
                "requires_approval": r.requires_approval, "risk": r.risk,
                "idempotency_key": r.idempotency_key, "request_hash": r.request_hash}

    def event_out(self, e: TaskEventRec) -> dict:
        return {"id": e.id, "task_id": e.task_id, "sequence": e.sequence, "kind": e.kind,
                "occurred_at": e.occurred_at, "summary": e.summary, "trace_id": e.trace_id}

    def attempt_out(self, a: TaskAttemptRec) -> dict:
        return {"id": a.id, "task_id": a.task_id, "worker_id": a.worker_id,
                "generation": a.generation, "started_at": a.started_at,
                "finished_at": a.finished_at, "outcome": a.outcome,
                "result_summary": a.result_summary}

    def _require(self, task_id: str) -> TaskRec:
        t = self.tasks.get(task_id)
        if t is None:
            raise TaskEngineError("not_found", "task not found", 404)
        return t


def _redact_args(arguments: dict) -> dict:
    """入参脱敏：密钥样值 → <redacted>；深度限 4。"""
    SENSITIVE = ("token", "secret", "password", "credential", "apikey", "api_key", "key")

    def walk(o, depth=0):
        if depth > 4:
            return "…"
        if isinstance(o, dict):
            return {k: ("<redacted>" if any(s in k.lower() for s in SENSITIVE)
                        else walk(v, depth + 1)) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(x, depth + 1) for x in o[:50]]
        if isinstance(o, str) and len(o) > 200:
            return o[:200] + "…"
        return o

    return walk(arguments)
