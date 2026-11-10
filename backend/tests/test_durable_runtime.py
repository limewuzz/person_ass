"""API transaction tests with a shared fake DB, not a PG runtime certification."""
import copy
import json
import pathlib
import uuid
import pytest
from fastapi.testclient import TestClient
import app as api
import service_container as container
from durable_state import DomainCheckpoint, decode
from auth import mint_token, ROLE_SCOPES
from dbpg.repository import MigrationRunner

ROOT = pathlib.Path(__file__).parents[2]


class FakeDatabase:
    def __init__(self):
        self.row = None
        self.commits = 0
        self.fail_commit = False

    def connect(self):
        db = self
        class Connection:
            pending = None
            def cursor(self): return Cursor(self)
            def commit(self):
                if db.fail_commit: raise RuntimeError('simulated outage')
                if self.pending is not None: db.row = copy.deepcopy(self.pending)
                self.pending = None
                db.commits += 1
            def rollback(self): self.pending = None
        class Cursor:
            rowcount = 1
            rows = []
            def __init__(self, conn): self.conn = conn
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute(self, sql, params=()):
                self.rows = []
                low = ' '.join(sql.lower().split())
                if low == 'select 1': self.rows = [(1,)]
                elif low.startswith('select version, checksum'):
                    self.rows = [(p.stem, MigrationRunner.file_checksum(p)) for p in sorted((ROOT/'dbpg/migrations').glob('*.sql'))]
                elif low.startswith('select version from'):
                    self.rows = [(p.stem,) for p in sorted((ROOT/'dbpg/migrations').glob('*.sql'))]
                elif 'information_schema.tables' in low:
                    self.rows = [(n,) for n in ['principals','resources','tasks','task_events','task_attempts','approvals','audit_events','outbox','task_leases','artifacts','runtime_state','ai_providers','conversations','conversation_messages','plugins','compute_runs','client_devices','client_sync_states','upload_tickets']]
                elif low.startswith('insert into runtime_state'):
                    self.conn.pending = copy.deepcopy(db.row) if db.row is not None else [0, 1, json.loads(params[0])]
                elif low.startswith('select revision, codec_version'):
                    self.rows = [copy.deepcopy(self.conn.pending)]
                elif low.startswith('update runtime_state'):
                    self.rowcount = int(self.conn.pending[0] == params[1])
                    if self.rowcount: self.conn.pending = [params[1] + 1, 1, json.loads(params[0])]
            def fetchone(self): return self.rows[0] if self.rows else None
            def fetchall(self): return self.rows
        return Connection()


@pytest.fixture
def durable(monkeypatch):
    codec = DomainCheckpoint(api)
    before = codec.dump()
    old = container.get_state()
    for name in ('tasks', 'events', 'attempts', '_idem', '_integrity'):
        getattr(api._engine, name).clear()
    api._approvals.approvals.clear()
    api._gateway.leases.clear()
    # State objects are intentionally shared with the real route closures.
    monkeypatch.setattr(container, '_state', container.AppState())
    db = FakeDatabase()
    state = container.swap_to_postgres(db.connect())
    assert state.engine is api._engine and state.store is api._store
    header = {'Authorization': 'Bearer ' + mint_token('test-secret-only-for-local-tests',
        sub=str(uuid.uuid4()), typ='actor', role='admin', scopes=sorted(ROLE_SCOPES['admin']))}
    client = TestClient(api.app, base_url='https://testserver', raise_server_exceptions=False)
    yield db, codec, client, header
    codec.load(before)
    monkeypatch.setattr(container, '_state', old)


def test_api_write_survives_domain_reload_and_new_database_connection(durable):
    db, codec, client, header = durable
    r = client.post('/api/v1/work-items', json={'title': 'durable work', 'kind': 'task'}, headers=header)
    assert r.status_code == 201, r.text
    wid = r.json()['id']
    api._engine.work_items.clear()  # Simulate losing the entire process ledger.
    container.swap_to_postgres(db.connect())
    assert client.get(f'/api/v1/work-items/{wid}', headers=header).json()['title'] == 'durable work'
    assert db.commits >= 3
    assert api._engine.work_items[wid].id == wid


def test_commit_failure_never_acknowledges_or_leaks_a_memory_write(durable):
    db, codec, client, header = durable
    before = codec.dump()
    db.fail_commit = True
    r = client.post('/api/v1/work-items', json={'title': 'must roll back', 'kind': 'task'}, headers=header)
    assert r.status_code == 503
    assert codec.dump() == before
    db.fail_commit = False
    assert not any(w.title == 'must roll back' for w in api._engine.work_items.values())


def test_uploaded_bytes_and_conversations_survive_reload_without_provider_secrets(durable):
    db, codec, client, header = durable
    r = client.post('/api/v1/conversations', json={'title': 'restored chat'}, headers=header)
    assert r.status_code == 201
    cid = r.json()['id']
    r = client.post(f'/api/v1/conversations/{cid}/messages', json={'content': 'persist me'}, headers={**header,'Idempotency-Key':'durable-message-key-0001'})
    assert r.status_code == 201
    api._engine.artifact_bytes['review-bytes'] = b'\x00\xffpayload'
    api._ai_hub._secret_vault['review-secret'] = 'never-serialize-provider-key'
    checkpoint = codec.dump()
    assert 'never-serialize-provider-key' not in checkpoint
    api._engine.artifact_bytes.clear()
    api._agent_os.conversations.clear()
    codec.load(checkpoint)
    assert api._engine.artifact_bytes['review-bytes'] == b'\x00\xffpayload'
    assert api._agent_os.conversations[cid].title == 'restored chat'
    api._ai_hub._secret_vault.pop('review-secret')


def test_codec_rejects_unknown_types_and_fields_before_state_mutation(durable):
    _, codec, _, _ = durable
    before = codec.dump()
    value = json.loads(before)
    value['values']['unexpected_namespace'] = {}
    with pytest.raises(ValueError): codec.load(value)
    assert codec.dump() == before
    with pytest.raises(ValueError): decode({'type':'record','name':'os.system','value':{}})


@pytest.mark.parametrize('outcome', ['SUCCEEDED','FAILED'])
def test_task_approval_lease_and_finish_survive_reload(durable, outcome):
    db, codec, c, human = durable
    from registry import RegistryService, ResourceRec
    if 'local-ledger' not in api._store.resources:
        # Persist explicit test-only admission before starting HTTP requests.
        container.get_state().durable.begin()
        RegistryService(api._store).register(ResourceRec('local-ledger','service','local','local','mac-mini'))
        container.get_state().durable.commit()
    payload = {'resource_id':'local-ledger','capability':'local.simulate',
               'arguments':{'outcome':outcome},'origin':{'channel':'web'},'dry_run':True}
    headers = {**human,'Idempotency-Key':str(uuid.uuid4())}
    accepted = c.post('/api/v1/tasks',json=payload,headers=headers)
    assert accepted.status_code == 202, accepted.text
    tid = accepted.json()['task_id']
    assert c.post('/api/v1/tasks',json=payload,headers=headers).json()['task_id'] == tid
    aid = next(a.id for a in api._approvals.approvals.values() if a.task_id == tid)
    assert c.post(f'/api/v1/approvals/{aid}/approve',headers=human).status_code == 200
    worker_id = 'local-review-worker'
    worker = {'Authorization':'Bearer '+mint_token('test-secret-only-for-local-tests',
        sub=worker_id,typ='worker',role='worker',scopes=sorted(ROLE_SCOPES['worker']))}
    assert c.post(f'/api/v1/workers/{worker_id}/heartbeat',headers=worker,json={
        'node_id':'mac-mini','version':'local-test','available_capabilities':['local.simulate'],
        'observed_at':'2026-11-10T00:00:00Z'}).status_code == 200
    claimed = c.post(f'/api/v1/workers/{worker_id}/claim',headers=worker,json={'limit':1,'capabilities':['local.simulate']})
    assert claimed.status_code == 200, claimed.text
    lease = next(t for t in claimed.json()['tasks'] if t['task_id'] == tid)
    body = {'generation':lease['generation'],'lease_token':lease['lease_token']}
    container.swap_to_postgres(db.connect())  # New connection and complete decode.
    assert c.post(f'/api/v1/workers/{worker_id}/tasks/{tid}/started',headers=worker,json=body).status_code == 200
    finished = c.post(f'/api/v1/workers/{worker_id}/tasks/{tid}/finish',headers=worker,json={**body,'outcome':outcome,'result_summary':'local test'})
    assert finished.status_code == 200, finished.text
    container.swap_to_postgres(db.connect())
    assert c.get(f'/api/v1/tasks/{tid}',headers=human).json()['state'] == outcome
    assert c.get(f'/api/v1/tasks/{tid}/events',headers=human).json()['items']


def test_cookie_csrf_works_with_frontend_header_and_rejects_foreign_origin():
    header = {'Authorization': 'Bearer ' + mint_token('test-secret-only-for-local-tests',
        sub=str(uuid.uuid4()), typ='actor', role='operator', scopes=sorted(ROLE_SCOPES['operator']))}
    c = TestClient(api.app, base_url='https://testserver')
    r = c.post('/api/v1/auth/session', json={'client_platform':'web'}, headers=header)
    assert r.status_code == 200
    assert 'httponly' in r.headers.get('set-cookie').lower()
    assert c.cookies.get('mwcp_csrf') == r.json()['csrf_token']
    request = {'title':'browser csrf','kind':'task'}
    good = {'X-MW-CSRF':r.json()['csrf_token'], 'Origin':'https://testserver'}
    assert c.post('/api/v1/work-items',json=request,headers=good).status_code == 201
    assert c.post('/api/v1/work-items',json=request,headers={**good,'Origin':'https://foreign.invalid'}).status_code == 403
    assert c.post('/api/v1/work-items',json=request,headers={'X-MW-CSRF':'wrong','Origin':'https://testserver'}).status_code == 403
