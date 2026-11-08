"""GPT-6 independent R7 negative tests: offline only; no production endpoints.
Run: R7_SOURCE_ROOT=/path/to/R7-src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q r8_negative_tests.py
"""
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

# GPT-6 R8 独立负向测试（逐字保留，仅 ROOT 解析改为从 __file__ 定位仓库根）
ROOT = Path(os.environ.get("R7_SOURCE_ROOT", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(ROOT / "backend"))
import probes
from probes import ProbeTarget, ProbeTargetRejected, register_target, run_probe_by_id, update_target
from registry import RegistryStore, ResourceRec

@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    monkeypatch.setenv("MWCP_PROBE_MODE", "test")


def store():
    s = RegistryStore()
    s.resources["svc.existing"] = ResourceRec("svc.existing", "service", "audit", "Existing", "mac-mini")
    return s


def target(path, *, kind="service", node_id="mac-mini"):
    return ProbeTarget(resource_id="svc.existing", kind=kind, node_id=node_id,
                       url="http://127.0.0.1:8123" + path)


def test_r8_p1_registered_kind_node_must_match_authoritative_resource_record():
    """Wrong kind/node must be rejected *at authorization*, not just when caller deviates from approval."""
    s = store()
    fake = target("/status", kind="artifact", node_id="ucloud-vps")
    with pytest.raises(ProbeTargetRejected, match="(resource|kind|node|mismatch)"):
        register_target(s, fake, allow_loopback=True)
    assert not getattr(s, "approved_probe_targets", {}).get("svc.existing")


def test_r8_p2_concurrent_optimistic_updates_must_not_both_commit_same_version(monkeypatch):
    """Force two writers past the version check before either writes; one must conflict."""
    s = store()
    register_target(s, target("/old"), allow_loopback=True)
    barrier = threading.Barrier(2)
    original = probes.validate_probe_target

    def before_validate(t, **kwargs):
        barrier.wait(timeout=4)
        return original(t, **kwargs)

    monkeypatch.setattr(probes, "validate_probe_target", before_validate)
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(update_target, s, target("/new-a" if i == 0 else "/new-b"),
                             expected_version=1, allow_loopback=True) for i in range(2)]
        results=[]
        for f in futures:
            try:
                results.append(("ok", f.result(timeout=8)))
            except ProbeTargetRejected as e:
                results.append(("rejected", str(e)))
    assert sum(s == "ok" for s,_ in results) == 1, "CAS version should permit exactly one writer"
    assert len([e for e in s.target_change_log if e['action']=='update']) == 1


def test_r8_p3_query_markers_are_not_copied_verbatim_into_audit_log():
    """Authorization audit should record hash/redacted endpoint, not verbatim query parameters."""
    s = store()
    marker = "NONSECRET_SENTINEL_FOR_REDACTION_TEST"
    register_target(s, target("/status?client_secret="+marker), allow_loopback=True)
    rendered = str(s.target_change_log)
    assert marker not in rendered, "Audit data should not store raw query values"
