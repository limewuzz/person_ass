from registry import RegistryService

"""GPT-6 independent R8 review negatives; all HTTP calls are MockTransport and no production network is accessed.

Set R8_SOURCE_ROOT to the extracted R8 source snapshot.
"""
import os
import sys
from pathlib import Path
import httpx
import pytest

# GPT-6 R9 独立负向测试（逐字保留，仅 ROOT 解析改为从 __file__ 定位仓库根）
ROOT = Path(os.environ.get("R8_SOURCE_ROOT", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(ROOT / "backend"))
import probes
from probes import (
    ProbeTarget,
    ProbeTargetRejected,
    register_target,
    run_probe_by_id,
    disable_target,
)
from registry import RegistryStore, ResourceRec


@pytest.fixture(autouse=True)
def test_mode(monkeypatch):
    monkeypatch.setenv("MWCP_PROBE_MODE", "test")


def make_store():
    store = RegistryStore()
    store.resources["svc.sandbox"] = ResourceRec(
        "svc.sandbox", "service", "owner-alpha", "Sandbox", "mac-mini"
    )
    return store


def target(path="/health"):
    return ProbeTarget(
        resource_id="svc.sandbox",
        kind="service",
        node_id="mac-mini",
        url="http://127.0.0.1:8123" + path,
    )


def mock_client():
    return httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"status": "ok"})
        )
    )


def test_r9_p1_owner_system_transfer_revokes_old_probe_authorization():
    """Changing the authoritative owner_system must invalidate an old owner-issued probe authorization."""
    store = make_store()
    register_target(store, target(), allow_loopback=True)
    RegistryService(store).transfer_owner("svc.sandbox", "owner-beta")
    with mock_client() as client:
        with pytest.raises(
            ProbeTargetRejected, match="owner|authoritative|mismatch|re-approv"
        ):
            run_probe_by_id(store, "svc.sandbox", allow_loopback=True, client=client)
    assert store.resources["svc.sandbox"].base_health == "unknown"


def test_r9_p2_disable_during_probe_prevents_stale_health_commit(monkeypatch):
    """Revoked approval may not publish a successful observation after the authorization version has changed."""
    store = make_store()
    register_target(store, target(), allow_loopback=True)
    original_validate = probes.validate_probe_target
    count = 0

    def revoke_between_authorize_and_request(t, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            disable_target(store, "svc.sandbox", expected_version=1)
        return original_validate(t, **kwargs)

    monkeypatch.setattr(
        probes, "validate_probe_target", revoke_between_authorize_and_request
    )
    with mock_client() as client:
        try:
            run_probe_by_id(store, "svc.sandbox", allow_loopback=True, client=client)
        except ProbeTargetRejected:
            pass
    assert store.approved_probe_targets["svc.sandbox"].enabled is False
    assert (
        store.resources["svc.sandbox"].base_health != "healthy"
    ), "Revoked target must not publish a healthy result"


def test_r9_p3_sensitive_path_segment_not_stored_raw_in_audit():
    """Query redaction cannot leak an equivalent synthetic credential embedded in the URL path."""
    store = make_store()
    marker = "NONSECRET_SYNTHETIC_PATH_CREDENTIAL_MARKER"
    register_target(store, target("/auth/" + marker + "/status"), allow_loopback=True)
    assert marker not in repr(store.target_change_log)
