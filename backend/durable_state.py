"""Bounded, versioned PostgreSQL checkpoint for the single-user domain engine.

No pickle, imports from stored input, credentials, or process/lock serialization.
One database row lock serializes requests across API processes. This deliberately
reuses the reviewed state machines rather than maintaining an unsynchronized
second set of business rules in normalized repository prototypes.
"""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
from functools import lru_cache

import anyio

MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
MAX_RESPONSE_BYTES = 24 * 1024 * 1024


@lru_cache(maxsize=1)
def record_types():
    import auth, registry, probes, taskengine, approvals, workergw
    from ai_hub import service as ai
    from agent_os import service as agent
    from worker_hub import service as worker
    from clients_sync import service as sync
    from integrations import service as integrations
    modules = (auth, registry, probes, taskengine, approvals, workergw,
               ai, agent, worker, sync, integrations)
    return {f'{m.__name__}.{k}': v for m in modules for k, v in vars(m).items()
            if isinstance(v, type) and v.__module__ == m.__name__ and
            (dataclasses.is_dataclass(v) or v is registry.ResourceRec)}


def encode(value):
    if value is None or type(value) in (str, int, float, bool):
        return value
    if type(value) is bytes:
        return {'type': 'bytes', 'value': base64.b64encode(value).decode('ascii')}
    if type(value) in (list, tuple, set):
        return {'type': type(value).__name__, 'value': [encode(x) for x in value]}
    if type(value) is dict:
        # Explicit pairs preserve tuple keys and prevent discriminator confusion.
        return {'type': 'dict', 'value': [[encode(k), encode(v)] for k, v in value.items()]}
    name = f'{type(value).__module__}.{type(value).__name__}'
    if name not in record_types():
        raise ValueError('Unsupported persistent record type')
    attrs = ([f.name for f in dataclasses.fields(value)] if dataclasses.is_dataclass(value)
             else list(type(value).__slots__))
    return {'type': 'record', 'name': name,
            'value': {k: encode(getattr(value, k)) for k in attrs}}


def decode(value):
    if value is None or type(value) in (str, int, float, bool):
        return value
    kind, data = value['type'], value['value']
    if kind == 'bytes':
        return base64.b64decode(data, validate=True)
    if kind in ('list', 'tuple', 'set'):
        return {'list': list, 'tuple': tuple, 'set': set}[kind](decode(x) for x in data)
    if kind == 'dict':
        return {decode(k): decode(v) for k, v in data}
    if kind == 'record':
        cls = record_types().get(value['name'])
        if cls is None:
            raise ValueError('Unknown persistent record type')
        fields = ({f.name for f in dataclasses.fields(cls)} if dataclasses.is_dataclass(cls)
                  else set(cls.__slots__))
        if set(data) != fields:
            raise ValueError('Persistent record fields differ from codec version')
        obj = object.__new__(cls)
        for k, v in data.items():
            object.__setattr__(obj, k, decode(v))
        return obj
    raise ValueError('Unknown persistent value type')


FIELDS = {
    '_fanout': ('plans','deliveries','idempotency','nonces','revision'),
    '_engine': ('work_items', '_wi_dedup', 'tasks', 'events', 'attempts', '_idem',
                '_seq', 'artifacts', 'artifact_bytes', '_integrity', 'audit_bus',
                '_audit_seq', 'admitted_generations', 'wire_payload_hashes'),
    '_store': ('_generation_seq', 'approved_probe_targets', 'target_change_log',
               'nodes', 'agents', 'capabilities'),
    '_approvals': ('approvals',),
    '_gateway': ('workers', 'leases', 'finished'),
    '_ai_hub': ('providers', 'models', 'routing_policy'),
    '_agent_os': ('agent_metadata', 'conversations', 'messages', '_msg_idem', 'plugins'),
    '_worker_hub': ('node_certs', 'pairings', 'compute_runs'),
    '_client_sync': ('devices', 'sync_states'),
    '_integrations': ('upload_tickets', 'download_tickets', 'artifact_mimes', 'knowledge_entries'),
}


class DomainCheckpoint:
    def __init__(self, api):
        self.api = api

    def dump(self):
        values = {name: {k: encode(getattr(getattr(self.api, name), k)) for k in keys}
                  for name, keys in FIELDS.items()}
        values['resources'] = encode(self.api._store.resources._data)
        values['revocations'] = encode(self.api._validator.revocations._revoked
                                       if self.api._validator else set())
        text = json.dumps({'codec_version': 2, 'values': values}, allow_nan=False,
                          separators=(',', ':'), ensure_ascii=False)
        if len(text.encode('utf-8')) > MAX_DOCUMENT_BYTES:
            raise ValueError('Persistent state exceeds configured 64 MiB ceiling')
        return text

    def recover_expired_leases(self):
        self.api._fanout.refresh()
        self.api._fanout._dirty.update(self.api._fanout.deliveries)
        engine, gateway = self.api._engine, self.api._gateway
        for task_id, lease in list(gateway.leases.items()):
            if lease.expires_at > gateway.clock():
                continue
            task = engine.tasks.get(task_id)
            if task and task.state in {"LEASED", "RUNNING"}:
                engine.transition(task_id, "NEEDS_RECONCILIATION", actor="restart-recovery",
                                  summary="Expired lease recovered; execution result uncertain")
                for attempt in engine.attempts.get(task_id, []):
                    if attempt.outcome is None:
                        attempt.state = "NEEDS_RECONCILIATION"
            del gateway.leases[task_id]

    def load(self, document):
        if isinstance(document, str):
            document = json.loads(document)
        if document.get('codec_version') not in (1,2):
            raise ValueError('Unsupported checkpoint version')
        values = dict(document['values'])
        if document['codec_version']==1 and '_fanout' not in values:
            values['_fanout']={k:encode(0 if k=='revision' else {}) for k in FIELDS['_fanout']}
        if set(values) != set(FIELDS) | {'resources', 'revocations'}:
            raise ValueError('Checkpoint namespaces differ from codec version')
        # Decode and validate everything before mutating any live domain object.
        decoded = {}
        for name, keys in FIELDS.items():
            if set(values[name]) != set(keys):
                raise ValueError('Checkpoint fields differ from codec version')
            decoded[name] = {k: decode(values[name][k]) for k in keys}
        resources, revocations = decode(values['resources']), decode(values['revocations'])
        for name, attrs in decoded.items():
            for k, value in attrs.items():
                setattr(getattr(self.api, name), k, value)
        self.api._store.resources._data = resources
        if self.api._validator:
            self.api._validator.revocations._revoked = revocations
        # Credential values are deliberately not checkpointed. Sessions also die
        # on process restart; production identity/session storage is another gate.
        ai = self.api._ai_hub
        for provider in ai.providers.values():
            provider.models = [ai.models[m.id] for m in provider.models]
            provider.has_secret_configured = provider.id in ai._secret_vault


class PgCheckpoint:
    def __init__(self, conn, codec):
        self.conn, self.codec = conn, codec
        self.revision = None

    def begin(self):
        with self.conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '3s'")
            cur.execute("SET LOCAL statement_timeout = '10s'")
            cur.execute("INSERT INTO runtime_state(id, codec_version, document) "
                        "VALUES ('control-plane',2,%s::jsonb) ON CONFLICT (id) DO NOTHING",
                        (self.codec.dump(),))
            cur.execute("SELECT revision, codec_version, document FROM runtime_state "
                        "WHERE id='control-plane' FOR UPDATE")
            row = cur.fetchone()
            if row is None or row[1] not in (1,2):
                raise RuntimeError('Runtime state unavailable')
            self.revision = row[0]
            self.codec.load(row[2])
            return self.codec.dump()

    def commit(self):
        with self.conn.cursor() as cur:
            cur.execute("UPDATE runtime_state SET revision=revision+1, codec_version=2, document=%s::jsonb, "
                        "updated_at=now() WHERE id='control-plane' AND revision=%s",
                        (self.codec.dump(), self.revision))
            if cur.rowcount != 1:
                raise RuntimeError('Runtime revision conflict')
            self.codec.api._fanout.project_sql(cur)
        self.conn.commit()
        self.codec.api._fanout._dirty.clear()


class DurableRequests:
    """Outer ASGI transaction: buffer finite responses until the commit succeeds.

    Current event endpoints are finite snapshots. A future continuous SSE stream
    must use its own read transaction; it must never hold this write lock forever.
    """
    def __init__(self, app):
        self.app = app
        self.lock = asyncio.Lock()

    async def __call__(self, scope, receive, send):
        from service_container import get_state
        state = get_state()
        if scope['type'] != 'http' or state.mode != 'postgres' or scope['path'] == '/api/v1/health/live' or (scope['path'].startswith('/api/v1/fanouts/') and scope['path'].endswith('/stream')):
            return await self.app(scope, receive, send)
        async with self.lock:
            durable = state.durable
            before = None
            messages, size = [], 0
            async def capture(message):
                nonlocal size
                size += len(message.get('body', b''))
                if size > MAX_RESPONSE_BYTES:
                    raise ValueError('Response exceeds configured bound')
                messages.append(message)
            try:
                before = await anyio.to_thread.run_sync(durable.begin)
                await self.app(scope, receive, capture)
                status = next(m['status'] for m in messages if m['type'] == 'http.response.start')
                if status >= 500:
                    await anyio.to_thread.run_sync(durable.conn.rollback)
                    durable.codec.load(before)
                    if status != 503:
                        from contract_wire import error_response
                        return await error_response(503, 'request_unavailable')(scope, receive, send)
                else:
                    await anyio.to_thread.run_sync(durable.commit)
            except Exception:
                await anyio.to_thread.run_sync(durable.conn.rollback)
                if before is not None:
                    durable.codec.load(before)
                from contract_wire import error_response
                return await error_response(503, 'persistence_unavailable')(scope, receive, send)
            except BaseException:
                # Cancellation must not leave an open transaction/row lock.
                with anyio.CancelScope(shield=True):
                    await anyio.to_thread.run_sync(durable.conn.rollback)
                if before is not None:
                    durable.codec.load(before)
                raise
            for message in messages:
                await send(message)
