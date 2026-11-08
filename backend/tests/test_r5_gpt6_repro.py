"""Review-only negative tests for MagicWorkshop R4. No production access.

Usage (from the extracted R4-01-SOURCE-SNAPSHOT root):
  MWCP_AUTH_SECRETS='dev-1:test-secret-only-for-local-tests' \
  PYTHONPATH=backend python -m pytest -q /path/to/R5-NEGATIVE-REPRO-TESTS.py

These tests are expected to FAIL against R4. GLM should fix code, then run
these alongside the original 53 tests. Network call in one probe uses
httpx.MockTransport; it makes no connection to the example public IP.
"""
# GPT-6 R4 独立评审提供的负向回归测试（逐字保留，仅 ROOT 解析改为从 __file__ 定位仓库根，
# 使其可在套件内任意 cwd 运行；原文件见 Drive R4-GPT6-INDEPENDENT-NEGATIVE-EVIDENCE.zip）
from pathlib import Path
import os
import re
import sys
import httpx
import pytest
from fastapi.testclient import TestClient

ROOT = Path(os.environ.get('R4_SOURCE_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(ROOT / 'backend'))
os.environ.setdefault('MWCP_AUTH_SECRETS', 'dev-1:test-secret-only-for-local-tests')

from auth import mint_token
from probes import ProbeTarget, run_probe, ProbeTargetRejected, PRODUCTION_ALLOWED_HOSTS
from registry import RegistryStore
import app


def _headers(sub, typ, role, scopes, jti):
    return {'Authorization': 'Bearer ' + mint_token(
        'test-secret-only-for-local-tests', sub=sub, typ=typ, role=role,
        scopes=scopes, jti=jti,
    )}


def test_worker_cannot_read_agent_detail():
    token = _headers('worker-test', 'worker', 'worker', ['worker:heartbeat'], 'r5-a')
    agent_id = next(iter(app._store.agents))
    resp = TestClient(app.app).get(f'/api/v1/agents/{agent_id}', headers=token)
    assert resp.status_code == 403, f'Worker incorrectly got HTTP {resp.status_code}'


def test_invalid_identity_type_is_rejected():
    token = _headers('unknown', 'not-an-identity-type', 'admin', ['admin:read'], 'r5-b')
    resp = TestClient(app.app).get('/api/v1/me', headers=token)
    assert resp.status_code == 401, f'Unknown typ incorrectly got HTTP {resp.status_code}'


def test_empty_production_allowlist_enforced_by_run_probe():
    assert not PRODUCTION_ALLOWED_HOSTS
    target = ProbeTarget(resource_id='r5-not-registered', url='http://8.8.8.8:2222/health')
    store = RegistryStore()
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
        with pytest.raises(ProbeTargetRejected):
            run_probe(target, store, client=client)
    assert target.resource_id not in store.resources


def test_pg_app_role_precedes_default_privilege_grants():
    txt = (ROOT / 'deploy/postgres/init/00-init-roles.sh').read_text()
    assert txt.index('CREATE ROLE mwcp_app') < txt.index('ALTER DEFAULT PRIVILEGES FOR ROLE mwcp_migrator')


def test_docker_copy_sources_are_in_context():
    import yaml
    path = ROOT / 'deploy/postgres/compose-v4.yml.proposal'
    api = yaml.safe_load(path.read_text())['services']['mwcp-api']
    context = (path.parent / api['build']['context']).resolve()
    dockerfile = context / api['build']['dockerfile']
    assert dockerfile.exists()
    sources = []
    for line in dockerfile.read_text().splitlines():
        if line.strip().startswith('COPY '):
            sources += line.split()[1:-1]
    assert all((context / src).exists() for src in sources), f'COPY sources not found in build context: {sources}'


def test_init_role_password_never_passed_as_process_argument():
    txt = (ROOT / 'deploy/postgres/init/00-init-roles.sh').read_text()
    assert '-v mig_pw="$MIG_PW"' not in txt
    assert '-v app_pw="$APP_PW"' not in txt


def test_auth_loader_reads_declared_secret_file():
    txt = (ROOT / 'backend/auth.py').read_text()
    assert 'MWCP_AUTH_SECRETS_FILE' in txt, 'Entrypoint file secret not consumed by auth loader'
