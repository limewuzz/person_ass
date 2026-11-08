"""Worker Gateway：心跳/租约/CAS/迟到拒绝/幂等 replay/过期回收。"""
import pytest
from taskengine import TaskEngine
from workergw import WorkerGateway


@pytest.fixture()
def gw():
    e = TaskEngine()
    g = WorkerGateway(e, clock=lambda: 1000.0)
    return e, g


def _seed_queued(e, n=1):
    ids = []
    for i in range(n):
        t, _ = e.create_task(principal_id="u", capability="probe.http.get",
                             capability_version=1, resource_id="svc.x",
                             idempotency_key=f"wk-{i}-0000000001",
                             arguments={"url": "http://x/"}, origin_channel="web")
        ids.append(t.id)
    return ids


def test_claim_requires_heartbeat(gw):
    e, g = gw
    _seed_queued(e)
    from taskengine import TaskEngineError
    with pytest.raises(TaskEngineError, match="heartbeat required"):
        g.claim("w-1", limit=1)


def test_full_task_lifecycle_via_worker(gw):
    e, g = gw
    (tid,) = _seed_queued(e)
    g.heartbeat("w-1", node_id="mac-mini", version="1",
                available_capabilities=["probe.http.get"])
    claimed = g.claim("w-1", limit=1)
    assert len(claimed) == 1 and claimed[0]["id"] == tid and claimed[0]["lease_token"]
    gen = claimed[0]["generation"]
    assert e.tasks[tid].state == "LEASED"
    g.started("w-1", tid, generation=gen, lease_token=claimed[0]["lease_token"])
    assert e.tasks[tid].state == "RUNNING"
    r = g.finish("w-1", tid, generation=gen, lease_token=claimed[0]["lease_token"],
                 outcome="SUCCEEDED", result_summary="ok")
    assert r["status"] == "ok" and e.tasks[tid].state == "SUCCEEDED"
    # 幂等 replay：同 (task, gen, token, outcome) 再 finish → replayed
    r2 = g.finish("w-1", tid, generation=gen, lease_token=claimed[0]["lease_token"],
                  outcome="SUCCEEDED")
    assert r2.get("replayed") is True


def test_late_result_after_generation_bump_rejected(gw):
    e, g = gw
    (tid,) = _seed_queued(e)
    g.heartbeat("w-1", node_id="n", version="1", available_capabilities=[])
    old = g.claim("w-1", limit=1)[0]
    # 模拟租约被回收并重新分配（新代数给 w-2）
    g.expire_lease(tid)
    g.heartbeat("w-2", node_id="n", version="1", available_capabilities=[])
    new = g.claim("w-2", limit=1)
    assert new and new[0]["generation"] > old["generation"]
    from taskengine import TaskEngineError
    with pytest.raises(TaskEngineError, match="late result"):
        g.finish("w-1", tid, generation=old["generation"],
                 lease_token=old["lease_token"], outcome="SUCCEEDED")


def test_expired_lease_cannot_start(gw):
    e, g = gw
    (tid,) = _seed_queued(e)
    g.heartbeat("w-1", node_id="n", version="1", available_capabilities=[])
    c = g.claim("w-1", limit=1)[0]
    g.expire_lease(tid)
    from taskengine import TaskEngineError
    with pytest.raises(TaskEngineError, match="expired"):
        g.started("w-1", tid, generation=c["generation"], lease_token=c["lease_token"])


def test_wrong_token_rejected(gw):
    e, g = gw
    (tid,) = _seed_queued(e)
    g.heartbeat("w-1", node_id="n", version="1", available_capabilities=[])
    c = g.claim("w-1", limit=1)[0]
    from taskengine import TaskEngineError
    with pytest.raises(TaskEngineError, match="late result"):
        g.finish("w-1", tid, generation=c["generation"], lease_token="forged",
                 outcome="SUCCEEDED")
