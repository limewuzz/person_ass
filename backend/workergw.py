"""Worker Gateway（本地 RC）：心跳 / claim(租约) / started / finish(CAS) / 迟到拒绝。

设计对应 PRD §Worker 与 contracts worker-protocol.schema；真实 PG 事务版见
dbpg/repository.py（NOT RUN）。安全要点：
- worker path id 必须等于 token subject（auth.require_worker_path_match）
- lease_token 只存哈希；lease 过期可回收；generation CAS 拒绝迟到结果
- 幂等 retry：同 (task, generation, outcome) 重复 finish 返回已受理
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field

from taskengine import TaskEngine, TaskEngineError, _now_iso

LEASE_TTL_SECONDS = 60
HEARTBEAT_TTL_SECONDS = 90


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class WorkerRec:
    worker_id: str
    node_id: str
    version: str = ""
    available_capabilities: list = field(default_factory=list)
    last_heartbeat_at: str = ""
    heartbeat_expires_at: float = 0.0
    registered_at: str = field(default_factory=_now_iso)


@dataclass
class LeaseRec:
    task_id: str
    worker_id: str
    generation: int
    lease_token_hash: str
    expires_at: float
    started: bool = False
    finished_outcome: str | None = None


class WorkerGateway:
    def __init__(self, engine: TaskEngine, clock=time.time) -> None:
        self.engine = engine
        self.clock = clock
        self._lock = threading.RLock()
        self.workers: dict[str, WorkerRec] = {}
        self.leases: dict[str, LeaseRec] = {}       # task_id -> active lease
        self.finished: dict[str, tuple] = {}        # task_id -> (worker,gen,token_hash,outcome) 幂等重放

    # ---------- 心跳 ----------
    def heartbeat(self, worker_id: str, *, node_id: str, version: str,
                  available_capabilities: list) -> dict:
        with self._lock:
            rec = self.workers.get(worker_id)
            if rec is None:
                rec = WorkerRec(worker_id=worker_id, node_id=node_id)
                self.workers[worker_id] = rec
            rec.node_id = node_id
            rec.version = version
            rec.available_capabilities = list(available_capabilities)
            rec.last_heartbeat_at = _now_iso()
            rec.heartbeat_expires_at = self.clock() + HEARTBEAT_TTL_SECONDS
            self.engine.audit(worker_id, "worker.heartbeat", worker_id, "ok")
            return {"status": "ok", "component": "worker-gateway"}

    def is_online(self, worker_id: str) -> bool:
        rec = self.workers.get(worker_id)
        return bool(rec and self.clock() < rec.heartbeat_expires_at)

    # ---------- 领取（租约）----------
    def claim(self, worker_id: str, *, limit: int, capabilities: list | None = None) -> list:
        if not self.is_online(worker_id):
            raise TaskEngineError("worker_offline", "heartbeat required before claim", 409)
        claimed: list = []
        with self._lock:
            for task in list(self.engine.tasks.values()):
                if len(claimed) >= max(1, min(int(limit), 10)):
                    break
                # 先回收过期租约（LEASED+过期 → 对账 → QUEUED），再判状态
                if task.id in self.leases:
                    lease = self.leases[task.id]
                    if self.clock() >= lease.expires_at:
                        self.engine.transition(task.id, "NEEDS_RECONCILIATION",
                                               actor=worker_id, summary="lease expired, recycled")
                        self.engine.transition(task.id, "QUEUED",
                                               actor="system", summary="requeued after lease expiry")
                        del self.leases[task.id]
                if task.state != "QUEUED":
                    continue
                gen = self.engine.bump_generation(task.id, actor=worker_id)
                token = secrets.token_urlsafe(24)
                self.leases[task.id] = LeaseRec(
                    task_id=task.id, worker_id=worker_id, generation=gen,
                    lease_token_hash=_hash_token(token),
                    expires_at=self.clock() + LEASE_TTL_SECONDS)
                self.engine.transition(task.id, "LEASED", actor=worker_id,
                                       summary=f"leased g{gen} by {worker_id}")
                self.engine.add_attempt(task.id, worker_id, gen)
                out = self.engine.task_out(task)
                claimed.append({**out, "lease_token": token})
        return claimed

    # ---------- started ----------
    def started(self, worker_id: str, task_id: str, *, generation: int,
                lease_token: str) -> dict:
        with self._lock:
            lease = self._lease_for(worker_id, task_id, generation, lease_token)
            task = self.engine.tasks.get(task_id)
            if task is None:
                raise TaskEngineError("not_found", "task not found", 404)
            if task.state == "LEASED":
                self.engine.transition(task_id, "RUNNING", actor=worker_id,
                                       summary=f"running g{generation}")
            lease.started = True
            return {"status": "ok", "component": "worker-gateway"}

    # ---------- finish（CAS + 迟到拒绝 + 幂等）----------
    def finish(self, worker_id: str, task_id: str, *, generation: int, lease_token: str,
               outcome: str, result_summary: str | None = None) -> dict:
        if outcome not in ("SUCCEEDED", "FAILED", "CANCELED", "EXPIRED"):
            raise TaskEngineError("bad_outcome", "outcome invalid")
        with self._lock:
            task = self.engine.tasks.get(task_id)
            if task is None:
                raise TaskEngineError("not_found", "task not found", 404)
            # 幂等 retry：finished 表命中（同 worker/同代/同 token/同结局）→ 已受理
            done = self.finished.get(task_id)
            if done == (worker_id, generation, _hash_token(lease_token), outcome):
                return {"status": "ok", "component": "worker-gateway", "replayed": True}
            lease = self.leases.get(task_id)
            # 迟到/被回收：租约不存在或代数不匹配 → 拒绝
            if (lease is None or lease.worker_id != worker_id
                    or lease.generation != generation
                    or _hash_token(lease_token) != lease.lease_token_hash):
                self.engine.audit(worker_id, "worker.finish_rejected", task_id,
                                  f"stale/invalid lease g{generation}", task.trace_id)
                raise TaskEngineError(
                    "stale_result",
                    "result rejected: lease expired, recycled, or belongs to another "
                    "generation (late result)", 409)
            if task.state in ("SUCCEEDED", "FAILED", "CANCELED", "EXPIRED"):
                raise TaskEngineError("already_finished", "task already terminal", 409)
            # 完成 attempt + 状态迁移
            for lst in self.engine.attempts.get(task_id, []):
                a = lst
                if a.worker_id == worker_id and a.outcome is None:
                    self.engine.finish_attempt(a.id, outcome=outcome,
                                               result_summary=result_summary)
                    break
            self.engine.transition(task_id, outcome, actor=worker_id,
                                   summary=f"finished g{generation} {outcome}")
            lease.finished_outcome = outcome
            del self.leases[task_id]
            self.finished[task_id] = (worker_id, generation,
                                      _hash_token(lease_token), outcome)
            return {"status": "ok", "component": "worker-gateway", "replayed": False}

    def expire_lease(self, task_id: str) -> bool:
        """测试/对账辅助：手动过期租约。"""
        with self._lock:
            lease = self.leases.get(task_id)
            if lease:
                lease.expires_at = 0.0
                return True
            return False

    def _lease_for(self, worker_id: str, task_id: str, generation: int,
                   lease_token: str) -> LeaseRec:
        lease = self.leases.get(task_id)
        if (lease is None or lease.worker_id != worker_id
                or lease.generation != generation
                or _hash_token(lease_token) != lease.lease_token_hash):
            raise TaskEngineError("stale_lease", "invalid or expired lease", 409)
        if self.clock() >= lease.expires_at:
            raise TaskEngineError("lease_expired", "lease expired", 409)
        return lease
