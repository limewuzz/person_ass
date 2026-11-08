"""GPT-6 independent R5 follow-up negative tests (R6 proposal).
Purely local: sockets and HTTP calls are mocked, no external network access.
Expected to fail against R5; GLM should fix in R6 and include as permanent regression.
"""
import os, socket, sys
from pathlib import Path
from unittest.mock import patch
import pytest
import httpx
# GPT-6 R6 独立负向测试（逐字保留，仅 ROOT 解析改为从 __file__ 定位仓库根）
ROOT = Path(os.environ.get('R5_SOURCE_ROOT', Path(__file__).resolve().parents[2])).resolve()
sys.path.insert(0,str(ROOT/'backend'))
from registry import RegistryStore, ResourceRec, RESOURCE_KINDS, seed_audit_baseline
from probes import ProbeTarget, run_probe, validate_probe_target, PRODUCTION_ALLOWED_HOSTS, ProbeTargetRejected


def test_probe_requires_target_registration_not_just_resource_exists(monkeypatch):
    monkeypatch.setenv('MWCP_PROBE_MODE','test')
    store = RegistryStore()
    store.resources['svc.existing'] = ResourceRec('svc.existing','service','demo','demo','us-server')
    target = ProbeTarget(resource_id='svc.existing',url='https://8.8.8.8/health')
    # Crucially, register_target() was NEVER called; any HTTP activity is mocked.
    transport = httpx.MockTransport(lambda request: httpx.Response(200,request=request))
    with httpx.Client(transport=transport,trust_env=False) as client:
        with pytest.raises(ProbeTargetRejected,match='target not registered'):
            run_probe(target,store,client=client)


def test_production_whitelist_cannot_bypass_private_resolved_ip(monkeypatch):
    monkeypatch.setenv('MWCP_PROBE_MODE','production')
    host = 'r6-probe.invalid'
    fake_dns = [(socket.AF_INET,socket.SOCK_STREAM,6,'',('10.88.0.42',0))]
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**kw:fake_dns)
    PRODUCTION_ALLOWED_HOSTS.add(host)
    try:
        with pytest.raises(ProbeTargetRejected,match='non-public'):
            validate_probe_target(ProbeTarget(resource_id='svc.existing',url=f'https://{host}/check'),production_mode=True)
    finally:
        PRODUCTION_ALLOWED_HOSTS.discard(host)


def test_audit_registry_resource_kinds_obey_contract_enum():
    store=RegistryStore();seed_audit_baseline(store)
    violations=[(r.id,r.kind) for r in store.resources.values() if r.kind not in RESOURCE_KINDS]
    assert not violations, f'Invalid seeded kind(s) under RESOURCE_KINDS: {violations}'
