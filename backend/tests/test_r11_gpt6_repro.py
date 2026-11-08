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
ROOT = Path(os.environ.get("R10_SOURCE_ROOT", Path(__file__).resolve().parents[2])).resolve()
sys.path.insert(0, str(ROOT / "backend"))
from registry import RegistryStore, ResourceRec  # noqa: E402
import probes  # noqa: E402


@pytest.fixture(autouse=True)
def probe_mode(monkeypatch):
    monkeypatch.setenv("MWCP_PROBE_MODE", "test")


def setup_store():
    store = RegistryStore()
    rid = "svc.sandbox"
    rec = ResourceRec(rid, "service", "owner-a", "test-only", "mac-mini")
    store.resources[rid] = rec
    target = probes.ProbeTarget(resource_id=rid, kind="service", node_id="mac-mini",
                                url="http://127.0.0.1:8123/health")
    probes.register_target(store, target, allow_loopback=True)
    return store, rec, rid


def test_external_registry_owner_writer_not_synchronized_with_probe_commit(monkeypatch):
    """Owner writes must participate in the same linearization protocol as probe commits.

    A separate simulated Registry writer updates the public ResourceRec while the
    probe holds _target_lock. This tests the *current mock store*, not an external API.
    """
    store, rec, rid = setup_store()
    writer_start = threading.Event()
    writer_done = threading.Event()
    old_guard = probes._owner_guard

    def guard_with_deterministic_interleaving(s, approved):
        old_guard(s, approved)
        if s._target_lock.locked():
            writer_start.set()
            assert writer_done.wait(2), "simulated registry writer did not run"

    monkeypatch.setattr(probes, "_owner_guard", guard_with_deterministic_interleaving)

    def writer():
        assert writer_start.wait(2), "commit guard was never entered"
        rec.owner_system = "owner-b"  # current RegistryStore permits unguarded write
        writer_done.set()

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200))) as client:
        try:
            probes.run_probe_by_id(store, rid, allow_loopback=True, client=client)
        except probes.ProbeTargetRejected:
            pass
    thread.join(2)
    assert not thread.is_alive()
    assert rec.owner_system == "owner-b"
    assert rec.base_health == "unknown", (
        "an owner transfer after the final check must not commit stale healthy")


def test_owner_aba_transfer_midflight_requires_monotonic_resource_generation():
    """Owner A->B->A during I/O must invalidate the old observation even if values match."""
    store, rec, rid = setup_store()

    def in_flight_http(req):
        rec.owner_system = "owner-b"
        rec.owner_system = "owner-a"  # ABA: values equal original, history differs
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(in_flight_http)) as client:
        try:
            probes.run_probe_by_id(store, rid, allow_loopback=True, client=client)
        except probes.ProbeTargetRejected:
            pass
    assert rec.owner_system == "owner-a"
    assert rec.base_health == "unknown", (
        "ABA migration during probe must invalidate prior authorization/result")
