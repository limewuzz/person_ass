"""R11-A：RegistryService 受控变更 / 单调代数 / 快照不可变 / 统一锁。"""

import threading
import pytest


@pytest.fixture(autouse=True)
def _probe_test_mode(monkeypatch):
    monkeypatch.setenv("MWCP_PROBE_MODE", "test")


from registry import RegistryService, RegistryStore, ResourceRec, ResourceSnapshot


def _store_with(rid="svc.x"):
    st = RegistryStore()
    st.resources[rid] = ResourceRec(rid, "service", "owner-a", "x", "mac-mini")
    return st


def test_service_register_assigns_monotonic_generation():
    st = RegistryStore()
    svc = RegistryService(st)
    a = svc.register(ResourceRec("a", "service", "o", "a", None))
    b = svc.register(ResourceRec("b", "service", "o", "b", None))
    assert b.generation > a.generation > 0


def test_transfer_owner_bumps_generation_and_revokes_probe_auth():
    import probes as P
    from probes import ProbeTarget, ProbeTargetRejected, register_target

    st = _store_with()
    svc = RegistryService(st)
    P.register_target(
        st,
        ProbeTarget(
            resource_id="svc.x", node_id="mac-mini", url="http://127.0.0.1:9/a"
        ),
        allow_loopback=True,
    )
    g0 = st.resources["svc.x"].generation
    svc.transfer_owner("svc.x", "owner-b")
    assert st.resources["svc.x"].generation > g0
    import httpx

    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200)), trust_env=False
    ) as client:
        with pytest.raises(ProbeTargetRejected, match="owner_system changed"):
            P.run_probe_by_id(st, "svc.x", client=client, allow_loopback=True)


def test_delete_recreate_never_reuses_generation():
    st = _store_with()
    svc = RegistryService(st)
    final_gen = svc.delete("svc.x")
    svc.recreate(ResourceRec("svc.x", "service", "owner-a", "x2", "mac-mini"))
    assert st.resources["svc.x"].generation > final_gen  # 严格更大，绝不复用


def test_expected_generation_cas_conflict():
    st = _store_with()
    svc = RegistryService(st)
    with pytest.raises(ValueError, match="generation conflict"):
        svc.move_node("svc.x", "us-server", expected_generation=999)


def test_snapshot_is_immutable_view():
    st = _store_with()
    svc = RegistryService(st)
    snap = svc.snapshot("svc.x")
    assert isinstance(snap, ResourceSnapshot)
    RegistryService(st).transfer_owner("svc.x", "someone-else")  # 内部变化不影响快照
    assert snap.owner_system == "owner-a"


def test_service_writer_vs_probe_commit_same_protocol():
    """受控 owner 写发生在探针网络阶段（锁外）→ 提交门必然作废旧观测。

    （受控写与提交共用同一把锁：若写发生在提交锁内，写者会排队到提交完成之后——
    那种时序下观测本身合法，无需作废；此处验证的是"提交前写已完成"的可见性。）
    """
    import httpx
    import probes as P
    from probes import ProbeTarget, ProbeTargetRejected, register_target

    st = _store_with()
    svc = RegistryService(st)
    P.register_target(
        st,
        ProbeTarget(
            resource_id="svc.x", node_id="mac-mini", url="http://127.0.0.1:9/a"
        ),
        allow_loopback=True,
    )
    gate_seen = threading.Event()

    def transport(req):
        svc.transfer_owner("svc.x", "owner-b")  # 受控写：网络阶段（提交锁外）
        gate_seen.set()
        return httpx.Response(200)

    with httpx.Client(
        transport=httpx.MockTransport(transport), trust_env=False
    ) as client:
        with pytest.raises(
            ProbeTargetRejected, match="owner_system changed|generation changed"
        ):
            P.run_probe_by_id(st, "svc.x", client=client, allow_loopback=True)
    assert gate_seen.is_set()
    assert st.resources["svc.x"].base_health == "unknown"


def test_aba_raw_writes_detected_by_write_rev():
    st = _store_with()
    rec = st.resources["svc.x"]
    r0 = rec.write_rev()
    with pytest.raises(AttributeError):
        rec.owner_system = "b"
    service = RegistryService(st)
    g0 = rec.generation
    service.transfer_owner("svc.x", "b")
    service.transfer_owner("svc.x", "owner-a")
    assert (
        rec.owner_system == "owner-a"
        and rec.write_rev() == r0 + 2
        and rec.generation > g0
    )
