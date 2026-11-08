"""TaskEngine：状态机 / 幂等(100并发) / 入参脱敏 / 事件与尝试。"""
import concurrent.futures as cf
import pytest
from taskengine import (ALLOWED_TRANSITIONS, TaskEngine, TaskEngineError,
                        _redact_args)


def _mk(engine, key="idem-key-000001", args=None, principal="user-a"):
    return engine.create_task(
        principal_id=principal, capability="probe.http.get", capability_version=1,
        resource_id="svc.x", idempotency_key=key, arguments=args or {"url": "http://x/health"},
        origin_channel="web")


def test_idempotent_replay_same_payload():
    e = TaskEngine()
    t1, r1 = _mk(e)
    t2, r2 = _mk(e)
    assert r1 is False and r2 is True and t1.id == t2.id


def test_idempotency_conflict_different_payload_409():
    e = TaskEngine()
    _mk(e)
    with pytest.raises(TaskEngineError) as ei:
        _mk(e, args={"url": "http://x/other"})
    assert ei.value.status == 409 and ei.value.code == "idempotency_conflict"


def test_100_concurrent_same_request_creates_exactly_one():
    e = TaskEngine()
    def submit(i):
        return e.create_task(
            principal_id="user-a", capability="probe.http.get", capability_version=1,
            resource_id="svc.x", idempotency_key="concurrent-key-0001",
            arguments={"url": "http://x/health"}, origin_channel="web")
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        results = list(ex.map(submit, range(100)))
    created = [t for t, replayed in results if not replayed]
    assert len(created) == 1
    assert len(e.tasks) == 1


def test_illegal_transition_rejected_409():
    e = TaskEngine()
    t, _ = _mk(e)  # QUEUED
    with pytest.raises(TaskEngineError) as ei:
        e.transition(t.id, "RUNNING")          # QUEUED→RUNNING 不合法（需先 LEASED）
    assert ei.value.status == 409 and ei.value.code == "illegal_transition"
    with pytest.raises(TaskEngineError):
        e.transition(t.id, "SUCCEEDED")
    e.transition(t.id, "CANCELED")             # QUEUED→CANCELED 合法
    with pytest.raises(TaskEngineError):       # 终态再动
        e.transition(t.id, "QUEUED")


def test_terminal_states_have_no_outgoing():
    assert all(not ALLOWED_TRANSITIONS[s] for s in
               ("SUCCEEDED", "FAILED", "CANCELED", "EXPIRED"))


def test_args_redaction_hides_secret_keys():
    out = _redact_args({"api_key": "sk-x", "nested": {"password": "p", "ok": 1}})
    assert out["api_key"] == "<redacted>" and out["nested"]["password"] == "<redacted>"
    assert out["nested"]["ok"] == 1


def test_work_item_dedup_on_source_pair():
    e = TaskEngine()
    a = e.create_work_item(title="t", kind="task", created_by="u",
                           source_system="rakazo", source_external_id="ext-1")
    b = e.create_work_item(title="t", kind="task", created_by="u",
                           source_system="rakazo", source_external_id="ext-1")
    assert a.id == b.id
    with pytest.raises(TaskEngineError):
        e.create_work_item(title="x" * 201, kind="task", created_by="u")


def test_events_and_trace_recorded():
    e = TaskEngine()
    t, _ = _mk(e)
    e.transition(t.id, "CANCELED", actor="u", summary="bye")
    evs = e.events[t.id]
    assert len(evs) == 2 and evs[0].kind == "created" and evs[1].kind == "state"
    assert all(x.trace_id == t.trace_id for x in evs)
