"""Independent R7 regressions for R6 white-list source. Local Mock only."""
import os
import sys
from pathlib import Path

import os as _os
sys.path.insert(0, str(Path(_os.environ.get('R7_SOURCE_ROOT', Path(__file__).resolve().parent / 'source')) / 'backend'))
import httpx
import pytest
from probes import ProbeTarget, ProbeTargetRejected, register_target, run_probe
from registry import RegistryStore, ResourceRec

@pytest.fixture(autouse=True)
def _local_probe_test_mode(monkeypatch):
    monkeypatch.setenv('MWCP_PROBE_MODE', 'test')


def _setup_store():
    store = RegistryStore()
    store.resources['svc.existing'] = ResourceRec(
        'svc.existing','service','test-owner','Test service','mac-mini')
    return store


def _client():
    return httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={'path':str(req.url)})))


def test_approved_url_query_cannot_be_swapped():
    store=_setup_store()
    approved=ProbeTarget(resource_id='svc.existing', url='http://127.0.0.1:8123/health?probe=passive', kind='service', node_id='mac-mini')
    register_target(store, approved, allow_loopback=True)
    substituted=ProbeTarget(resource_id='svc.existing', url='http://127.0.0.1:8123/health?command=unexpected', kind='service', node_id='mac-mini')
    with _client() as client:
        with pytest.raises(ProbeTargetRejected, match='target mismatch'):
            run_probe(substituted, store, client=client, allow_loopback=True)


def test_approved_target_cannot_claim_different_node_or_kind():
    store=_setup_store()
    approved=ProbeTarget(resource_id='svc.existing', url='http://127.0.0.1:8123/status', kind='service', node_id='mac-mini')
    register_target(store, approved, allow_loopback=True)
    spoofed=ProbeTarget(resource_id='svc.existing', url='http://127.0.0.1:8123/status', kind='artifact', node_id='ucloud-vps')
    with _client() as client:
        with pytest.raises(ProbeTargetRejected, match='(kind|node|target mismatch)'):
            run_probe(spoofed, store, client=client, allow_loopback=True)


def test_new_registration_cannot_silently_overwrite_approval():
    store=_setup_store()
    approved=ProbeTarget(resource_id='svc.existing', url='http://127.0.0.1:8123/old', kind='service', node_id='mac-mini')
    swapped=ProbeTarget(resource_id='svc.existing', url='http://127.0.0.1:8123/new', kind='service', node_id='mac-mini')
    register_target(store, approved, allow_loopback=True)
    with pytest.raises(ProbeTargetRejected,match='(already|change|approval|conflict)'):
        register_target(store, swapped, allow_loopback=True)
