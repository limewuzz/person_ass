"""R11 independent negatives against unmodified R10 snapshot.

No external network: all HTTP uses httpx.MockTransport.
Before running, set R10_SOURCE_ROOT=/absolute/path/to/extracted/R10-source.
Expected on R10: 2 FAILED. Future fix: retain test semantics and make both pass.
"""

import os
import sys
import threading
from pathlib import Path

import httpx
import pytest

# GPT-6 R11 独立负向测试（逐字保留，仅 ROOT 解析改为从 __file__ 定位仓库根）
ROOT = Path(
    os.environ.get("R10_SOURCE_ROOT", Path(__file__).resolve().parents[2])
).resolve()
sys.path.insert(0, str(ROOT / "backend"))
from registry import RegistryService, RegistryStore, ResourceRec  # noqa: E402
import probes  # noqa: E402


@pytest.fixture(autouse=True)
def probe_mode(monkeypatch):
    monkeypatch.setenv("MWCP_PROBE_MODE", "test")


def setup_store():
    store = RegistryStore()
    rid = "svc.sandbox"
    rec = ResourceRec(rid, "service", "owner-a", "test-only", "mac-mini")
    store.resources[rid] = rec
    target = probes.ProbeTarget(
        resource_id=rid,
        kind="service",
        node_id="mac-mini",
        url="http://127.0.0.1:8123/health",
    )
    probes.register_target(store, target, allow_loopback=True)
    return store, rec, rid


def test_external_registry_owner_writer_not_synchronized_with_probe_commit(monkeypatch):
    """A controlled writer blocks at the commit lock, then clears old observation on transfer."""
    store, rec, rid = setup_store()
    with pytest.raises(AttributeError):
        rec.owner_system = "owner-b"
    writer_start = threading.Event()
    writer_done = threading.Event()
    blocked = threading.Event()
    old_guard = probes._owner_guard

    def guard(s, approved):
        old_guard(s, approved)
        if s._target_lock.locked():
            writer_start.set()
            assert not writer_done.wait(0.05), "writer bypassed the commit lock"
            blocked.set()

    monkeypatch.setattr(probes, "_owner_guard", guard)

    def writer():
        assert writer_start.wait(2)
        RegistryService(store).transfer_owner(rid, "owner-b")
        writer_done.set()

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200))
    ) as client:
        probes.run_probe_by_id(store, rid, allow_loopback=True, client=client)
    thread.join(2)
    assert blocked.is_set() and writer_done.is_set() and not thread.is_alive()
    assert rec.owner_system == "owner-b" and rec.base_health == "unknown"


def test_owner_aba_transfer_midflight_requires_monotonic_resource_generation():
    """Owner A->B->A during I/O must invalidate the old observation even if values match."""
    store, rec, rid = setup_store()

    def in_flight_http(req):
        RegistryService(store).transfer_owner(rid, "owner-b")
        RegistryService(store).transfer_owner(
            rid, "owner-a"
        )  # ABA: values equal original, history differs
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(in_flight_http)) as client:
        try:
            probes.run_probe_by_id(store, rid, allow_loopback=True, client=client)
        except probes.ProbeTargetRejected:
            pass
    assert rec.owner_system == "owner-a"
    assert (
        rec.base_health == "unknown"
    ), "ABA migration during probe must invalidate prior authorization/result"
