from registry import RegistryService

"""GPT-6 R10 independent negative tests against the unmodified R9 archive.
All HTTP calls use httpx.MockTransport; no external network or production services.
"""
import sys
from pathlib import Path
import pytest
import httpx

# GPT-6 R10 独立负向测试（逐字保留，仅 ROOT 解析改为从 __file__ 定位仓库根）
import os

ROOT = Path(os.environ.get("R10_SOURCE_ROOT", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(ROOT / "backend"))
from registry import RegistryStore, ResourceRec
from probes import ProbeTarget, register_target, run_probe_by_id, disable_target


@pytest.fixture(autouse=True)
def test_mode(monkeypatch):
    monkeypatch.setenv("MWCP_PROBE_MODE", "test")


def fixture():
    store = RegistryStore()
    store.resources["svc.sandbox"] = ResourceRec(
        "svc.sandbox", "service", "owner-alpha", "sandbox only", "mac-mini"
    )
    target = ProbeTarget(
        resource_id="svc.sandbox",
        kind="service",
        node_id="mac-mini",
        url="http://127.0.0.1:8123/health",
    )
    register_target(store, target, allow_loopback=True)
    return store


def test_r10_p1_owner_change_midflight_must_discard_health():
    """Current Registry owner_system changed mid-probe must invalidate old observation."""
    store = fixture()

    def during_probe(request):
        # mutation during HTTP probe AFTER authorization precheck; no real network
        RegistryService(store).transfer_owner("svc.sandbox", "owner-beta")
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(during_probe)) as client:
        try:
            run_probe_by_id(store, "svc.sandbox", allow_loopback=True, client=client)
        except ValueError:
            pass
    assert store.resources["svc.sandbox"].owner_system == "owner-beta"
    assert (
        store.resources["svc.sandbox"].base_health == "unknown"
    ), "Old owner authorization must not commit new health after owner migration"


def test_r10_p2_disable_after_commit_precheck_must_not_write_health():
    """Disable in the gap between version recheck and write must discard result."""
    store = fixture()
    calls = [0]

    def event_clock():
        calls[0] += 1
        # R9 run_probe invokes clock() for observed_at immediately AFTER its
        # approval gate, but BEFORE updating ResourceRec. Deterministic event.
        if calls[0] == 1:
            disable_target(store, "svc.sandbox", expected_version=1)
        return 1700000000.0 + calls[0]

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"ok": True})
        )
    ) as client:
        try:
            run_probe_by_id(
                store,
                "svc.sandbox",
                allow_loopback=True,
                clock=event_clock,
                client=client,
            )
        except ValueError:
            pass
    assert store.approved_probe_targets["svc.sandbox"].enabled is False
    assert (
        store.resources["svc.sandbox"].base_health == "unknown"
    ), "Result written after a concurrent revoke must not make health healthy"


def test_r10_p3_short_secret_bearing_path_segment_must_not_leak():
    """A synthetic short identifier following /auth/ is still sensitive."""
    store = RegistryStore()
    store.resources["svc.sandbox"] = ResourceRec(
        "svc.sandbox", "service", "owner-alpha", "sandbox only", "mac-mini"
    )
    marker = "SYN8Ab9"  # synthetic, NOT any live credential
    t = ProbeTarget(
        resource_id="svc.sandbox",
        kind="service",
        node_id="mac-mini",
        url=f"http://127.0.0.1:8123/auth/{marker}/status",
    )
    register_target(store, t, allow_loopback=True)
    assert marker not in repr(
        store.target_change_log
    ), "Audit should redact potentially sensitive short values in auth path segments"
