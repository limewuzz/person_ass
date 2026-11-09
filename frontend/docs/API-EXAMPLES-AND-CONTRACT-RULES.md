# MagicWorkshop 1.1 API Examples & Contract Rules

**These are synthetic local fixtures, not real live service data.** Compatible with the accompanying proposed OpenAPI 3.1 definitions. `DataSourceMeta.data_mode` and `freshness` are independent. The v0.4 31-path contract remains the original behavioral reference for existing routes.

## 1. `GET /api/v1/ui/bootstrap` — HTTP 200 application/json

```json
{
  "contract_version": "1.1.0-draft-local",
  "server_time": "2026-11-09T00:00:00+09:00",
  "app_mode": "LOCAL_MOCK",
  "identity": {"id":"11111111-1111-4111-8111-111111111111","role":"actor","display_name":"Local Demo User","allowed_scopes":["registry:read","tasks:read","approvals:read"]},
  "features": {
    "registry_view": {"status":"MOCK_ONLY","reason":"No production source has been authorized","min_phase":"P1"},
    "tasks_mock": {"status":"MOCK_ONLY","reason":"Local simulator only","min_phase":"P2"},
    "production_probe": {"status":"DISABLED","reason":"Production allowlist is empty and approval is absent","min_phase":"P2"},
    "colab_integration": {"status":"NOT_IMPLEMENTED","reason":"No account authorization or live connector","min_phase":"P3"}
  },
  "source_meta": {"data_mode":"MOCK","freshness":"UNKNOWN","source_system":"magicworkshop-local-fixture","observed_at":null,"received_at":null,"ttl_seconds":null,"reason_code":"LOCAL_SIMULATOR","as_of":"2026-11-09T00:00:00+09:00"}
}
```

## 2. `GET /api/v1/dashboard/summary` — HTTP 200 application/json

```json
{
  "nodes": {"items":[{"id":"node.us","name":"US Primary (Demo)","role":"PRIMARY","health":"unknown","stale":true,"source":"mock-seed","observed_at":null,"last_seen_at":null}],"next_cursor":null},
  "task_counts":{"QUEUED":null,"RUNNING":null,"FAILED":null},
  "approval_counts":{"PENDING":null},
  "recent_events":[],
  "source_meta":{"data_mode":"MOCK","freshness":"UNKNOWN","source_system":"mock-seed","observed_at":null,"received_at":null,"ttl_seconds":null,"reason_code":"NO_LIVE_METRICS","as_of":"2026-11-09T00:00:00+09:00"}
}
```

Do not paint the node green or display missing count as `0` in the dashboard. `health=unknown`, `stale=true`, `data_mode=MOCK` are not evidence of a live outage either.

## 3. `GET /api/v1/workflows` (same response for read-only catalog endpoints) — HTTP 200

```json
{
 "items":[{"id":"wf.demo.local","title":"Mock workflow","summary":"Synthetic catalog entry, never triggers an existing cron","source_system":"local-fixture","source_meta":{"data_mode":"MOCK","freshness":"UNKNOWN","source_system":"local-fixture","observed_at":null,"received_at":null,"ttl_seconds":null,"reason_code":"LOCAL_ONLY","as_of":"2026-11-09T00:00:00+09:00"},"route_ref":null,"enabled":false}],
 "next_cursor":null,
 "source_meta":{"data_mode":"MOCK","freshness":"UNKNOWN","source_system":"local-fixture","observed_at":null,"received_at":null,"ttl_seconds":null,"reason_code":"LOCAL_ONLY","as_of":"2026-11-09T00:00:00+09:00"}
}
```

For `network/links`, `models`, `projects`, `compute/runs`, `knowledge`, use the same `DisplayRecordList` format. Unconnected integrations in a non-mock production UI should return `items:[]`, `source_meta.data_mode=UNAVAILABLE`, and explain why; never invent real observations.

## 4. `GET /api/v1/events/history` — HTTP 200 JSON (not SSE)

```json
{
 "items": [], "next_cursor": null,
 "source_meta":{"data_mode":"UNAVAILABLE","freshness":"UNKNOWN","source_system":"unconnected","observed_at":null,"received_at":null,"ttl_seconds":null,"reason_code":"NOT_CONFIGURED","as_of":"2026-11-09T00:00:00+09:00"}
}
```

Existing `/api/v1/events` is `text/event-stream` with event IDs/Last-Event-ID. Do not use the JSON history response on its SSE path. Browser errors/disconnect must show `Live paused` and a safe retry policy.

## 5. `POST /api/v1/tasks` — P2 Local Mock only

Request header: `Idempotency-Key: e2e-demo-task-00000001` (synthetic)

```json
{"capability":"mock.health.read","resource_id":"node.us","arguments":{"mode":"mock"},"dry_run":true,"origin":{"channel":"web","source_ref":"magicworkshop-local"}}
```

**Important**: This is an illustrative synthetic request matching the v0.4 `Origin` schema (`channel`, `source_ref`). Do not use a capability string or resource ID from the real production system. A successful mock server should follow the existing v0.4 `TaskAccepted` envelope (task_id, state, trace_id, poll_url, replayed), return `202` for initial acceptance, and enforce server-side idempotency and authorization. Disallowed production-side adapters must remain disabled regardless of the browser's request.

## 6. Error responses and UI policy

```json
{"error":{"code":"DEPENDENCY_UNAVAILABLE","message":"The local data source is not configured","details_redacted":{}},"trace_id":"22222222-2222-4222-8222-222222222222"}
```

The error response must never include raw target URL path/query, credentials or endpoint auth headers. `401` is not logged-in; `403` is not authorized; `404` is hidden or missing; `409` is version/idempotency conflict; `503` is dependency unavailable. The frontend should not reinterpret a failed request as cached `LIVE` data.

## 7. Contract negotiation and implementation scope

- `41 paths / 43 operations` is the **full planning interface**, not 43 already-implemented server operations. GLM reports per-operation status `IMPLEMENTED/TESTED/NOT_IMPLEMENTED` and `MOCK_ONLY/LIVE_UNAPPROVED` independently.
- New 10 read-only paths in v1.1 are candidates for local RC implementation; **all production probes and legacy live adapter calls are still forbidden**.
- `Resource.generation/lifecycle_state` are optional additions for v0.4 compatibility; production PG persistence requires transaction and R11 ABA verification later.
- `CONTRACT-LOCK.json` is finalized by GLM after OAS route+schema validation; Codex must pin exact bytes SHA-256 before generating client and building E2E.
- For anything not defined by the contract, do not silently invent a field. Use a change request with JSON schema, page usage and backward compatibility evidence.
