"""审批域（本地 RC）：策略分级 / payload 哈希 / 过期 / 一次性消费 / 二次确认。

只有纯本地 MOCK 动作可被模拟执行（capability 白名单 READ/LOW 且 dry_run）；
HIGH 及任何旧服务写一律不可调用（策略硬编码在服务端，不依赖 UI 禁用）。
"""

from __future__ import annotations

from datetime import datetime, timezone
import secrets
import threading
import uuid
from dataclasses import dataclass, field

from taskengine import TaskEngine, TaskEngineError, _now_iso, _payload_hash

APPROVAL_STATES = {"pending", "approved", "rejected", "expired", "consumed", "canceled"}
RISK_LEVELS = {"READ", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
APPROVAL_TTL_SECONDS = 600  # 审批单有效期（本地 RC 默认）
EXECUTABLE_RISKS = {"READ", "LOW"}  # 仅这些风险等级在本地 mock 可消费执行


@dataclass
class ApprovalRec:
    id: str
    task_id: str
    risk: str
    payload_hash: str
    state: str = "pending"
    created_at: str = field(default_factory=_now_iso)
    expires_at: float = 0.0
    expires_at_iso: str = ""
    consumed_at: str | None = None
    confirm_token: str = ""  # 一次性消费令牌（只存哈希）
    decided_by: str | None = None


class ApprovalService:
    def __init__(self, engine: TaskEngine, clock) -> None:
        self.engine = engine
        self.clock = clock
        self._lock = engine._lock
        engine.approval_service = self
        self.approvals: dict[str, ApprovalRec] = {}

    def create_for_task(self, task, *, risk: str) -> ApprovalRec:
        if risk not in RISK_LEVELS:
            raise TaskEngineError("bad_risk", f"risk in {sorted(RISK_LEVELS)}")
        with self._lock:
            # 同任务重复申请：pending 存在则幂等返回
            for a in self.approvals.values():
                if a.task_id == task.id and a.state == "pending":
                    return a
            rec = ApprovalRec(
                id=str(uuid.uuid4()),
                task_id=task.id,
                risk=risk,
                payload_hash=task.request_hash,
                expires_at=self.clock() + APPROVAL_TTL_SECONDS,
                expires_at_iso=datetime.fromtimestamp(
                    self.clock() + APPROVAL_TTL_SECONDS, timezone.utc
                ).isoformat(),
                confirm_token=secrets.token_urlsafe(16),
            )
            self.approvals[rec.id] = rec
            self.engine.audit(
                "system",
                "approval.created",
                rec.id,
                f"risk={risk} task={task.id}",
                task.trace_id,
            )
            return rec

    def decide(self, approval_id: str, *, decision: str, actor: str) -> ApprovalRec:
        """approve/reject：过期拒绝、状态机拒绝、审计。"""
        if decision not in ("approved", "rejected"):
            raise TaskEngineError("bad_decision", "decision must be approved|rejected")
        with self._lock:
            rec = self._require(approval_id)
            task = self.engine._require(rec.task_id)
            self.engine.verify_integrity(task)
            if task.state != "WAITING_APPROVAL":
                raise TaskEngineError(
                    "approval_state", "task no longer waiting for approval", 409
                )
            if rec.state == "pending" and self.clock() >= rec.expires_at:
                rec.state = "expired"
                self.engine.transition(rec.task_id, "EXPIRED", actor=actor)
                self.engine.audit(actor, "approval.expired", rec.id, "ttl exceeded")
                raise TaskEngineError("approval_expired", "approval ttl exceeded", 409)
            if rec.state != "pending":
                raise TaskEngineError(
                    "approval_state", f"approval is {rec.state}, not pending", 409
                )
            rec.state = decision
            rec.decided_by = actor
            self.engine.audit(
                actor, f"approval.{decision}", rec.id, f"task={rec.task_id}", ""
            )
            task = self.engine.tasks.get(rec.task_id)
            if task is not None:
                if decision == "approved":
                    self.engine.transition(
                        rec.task_id,
                        "QUEUED",
                        actor=actor,
                        summary="approved; queued for execution",
                    )
                else:
                    self.engine.transition(
                        rec.task_id,
                        "CANCELED",
                        actor=actor,
                        summary="rejected by approver",
                    )
            return rec

    def consume(
        self,
        approval_id: str,
        *,
        confirm_token: str,
        payload_hash: str,
        actor: str = "worker",
    ) -> ApprovalRec:
        """一次性消费：approved → consumed；payload 哈希不符 = 篡改拒绝。"""
        with self._lock:
            rec = self._require(approval_id)
            if rec.state == "consumed":
                raise TaskEngineError(
                    "already_consumed", "approval one-time consumed", 409
                )
            if rec.state != "approved":
                raise TaskEngineError("not_approved", f"approval is {rec.state}", 409)
            if confirm_token != rec.confirm_token:
                self.engine.audit(
                    actor, "approval.consume_rejected", rec.id, "bad confirm token"
                )
                raise TaskEngineError("bad_confirm", "confirm token mismatch", 403)
            if payload_hash != rec.payload_hash:
                self.engine.audit(
                    actor,
                    "approval.consume_rejected",
                    rec.id,
                    "payload hash mismatch (tampered?)",
                )
                raise TaskEngineError(
                    "payload_tampered",
                    "payload hash mismatch with approved request",
                    409,
                )
            task = self.engine._require(rec.task_id)
            self.engine.verify_integrity(task)
            if self.clock() >= rec.expires_at:
                rec.state = "expired"
                raise TaskEngineError(
                    "approval_expired", "approval expired before execution", 409
                )
            local_medium = (
                rec.risk == "MEDIUM"
                and task.capability == "local.simulate"
                and task.resource_id == "local-ledger"
                and task.dry_run
            )
            if rec.risk not in EXECUTABLE_RISKS and not local_medium:
                raise TaskEngineError(
                    "risk_not_executable",
                    f"risk {rec.risk} cannot execute in local mock (server-side policy)",
                    403,
                )
            rec.state = "consumed"
            rec.consumed_at = _now_iso()
            self.engine.audit(actor, "approval.consumed", rec.id, "executed(mock)", "")
            return rec

    def sweep(self):
        with self._lock:
            for rec in list(self.approvals.values()):
                task = self.engine.tasks.get(rec.task_id)
                if (
                    rec.state in {"pending", "approved"}
                    and self.clock() >= rec.expires_at
                ):
                    rec.state = "expired"
                    if task and task.state in {"WAITING_APPROVAL", "QUEUED"}:
                        self.engine.transition(
                            task.id,
                            "EXPIRED",
                            actor="local-policy",
                            summary="approval TTL expired",
                        )

    def invalidate_task(self, task_id):
        with self._lock:
            for rec in self.approvals.values():
                if rec.task_id == task_id and rec.state in {"pending", "approved"}:
                    rec.state = "expired"

    def consume_for_task(self, task):
        with self._lock:
            rec = next(
                (
                    r
                    for r in self.approvals.values()
                    if r.task_id == task.id and r.state == "approved"
                ),
                None,
            )
            if rec is None:
                raise TaskEngineError(
                    "not_approved", "no valid approval bound to task", 409
                )
            if rec.payload_hash != task.request_hash:
                raise TaskEngineError(
                    "payload_tampered", "approval request hash mismatch", 409
                )
            return self.consume(
                rec.id, confirm_token=rec.confirm_token, payload_hash=task.request_hash
            )

    def approval_out(self, r):
        task = self.engine._require(r.task_id)
        return {
            "id": r.id,
            "task_id": r.task_id,
            "state": r.state.upper(),
            "risk": r.risk,
            "created_at": r.created_at,
            "expires_at": r.expires_at_iso,
            "requester_ref": task.principal_id,
            "scope": "仅新平台本地合成账本",
            "action": task.capability,
            "resource_id": task.resource_id,
            "arguments_redacted": task.args_redacted,
            "target_generation": getattr(self.engine, "admitted_generations", {}).get(
                task.id
            ),
        }

    def _require(self, approval_id: str) -> ApprovalRec:
        a = self.approvals.get(approval_id)
        if a is None:
            raise TaskEngineError("not_found", "approval not found", 404)
        return a
