"""审批域：自动创建 / 决策 / 过期 / 篡改 / 一次性 / HIGH 服务端硬拒。"""
import pytest
from approvals import ApprovalService
from taskengine import TaskEngine, TaskEngineError
import time


@pytest.fixture()
def svc():
    e = TaskEngine()
    return e, ApprovalService(e, clock=time.time)


def _task(e, *, requires=False, risk="READ", args=None):
    t, _ = e.create_task(principal_id="u", capability="probe.http.get",
                         capability_version=1, resource_id="svc.x",
                         idempotency_key="ap-key-00000001", arguments=args or {"a": 1},
                         origin_channel="web", requires_approval=requires, risk=risk)
    return t


def test_pending_approval_blocks_queue_and_approve_unblocks(svc):
    e, a = svc
    t = _task(e, requires=True)
    assert t.state == "WAITING_APPROVAL"
    rec = a.create_for_task(t, risk="READ")
    a.decide(rec.id, decision="approved", actor="approver-1")
    assert e.tasks[t.id].state == "QUEUED"


def test_reject_cancels_task(svc):
    e, a = svc
    t = _task(e, requires=True)
    rec = a.create_for_task(t, risk="READ")
    a.decide(rec.id, decision="rejected", actor="approver-1")
    assert e.tasks[t.id].state == "CANCELED"


def test_expiry_rejected(svc):
    e, a = svc
    class FakeClock:
        t = 1000.0
        def __call__(self): return self.t
    a2 = ApprovalService(e, clock=FakeClock())
    t = _task(e, requires=True)
    rec = a2.create_for_task(t, risk="READ")
    a2.clock.t += 10000
    with pytest.raises(TaskEngineError, match="ttl exceeded"):
        a2.decide(rec.id, decision="approved", actor="x")


def test_consume_tamper_and_one_time(svc):
    e, a = svc
    t = _task(e, requires=True)
    rec = a.create_for_task(t, risk="READ")
    a.decide(rec.id, decision="approved", actor="x")
    with pytest.raises(TaskEngineError, match="payload hash mismatch"):
        a.consume(rec.id, confirm_token=rec.confirm_token,
                  payload_hash="f" * 64, actor="worker")
    a.consume(rec.id, confirm_token=rec.confirm_token, payload_hash=rec.payload_hash)
    with pytest.raises(TaskEngineError, match="already_consumed"):
        a.consume(rec.id, confirm_token=rec.confirm_token,
                  payload_hash=rec.payload_hash)


def test_high_risk_never_executable_server_side(svc):
    e, a = svc
    t = _task(e, requires=True, risk="HIGH")
    rec = a.create_for_task(t, risk="HIGH")
    a.decide(rec.id, decision="approved", actor="x")
    with pytest.raises(TaskEngineError, match="risk_not_executable"):
        a.consume(rec.id, confirm_token=rec.confirm_token, payload_hash=rec.payload_hash)
