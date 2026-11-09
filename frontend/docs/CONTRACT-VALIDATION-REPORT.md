# MagicWorkshop Contract v1.1 — validation report

Generated for local agent handoff, NOT deployed and NOT evidence of backend implementation.

- Source: original v0.4 `openapi.yaml` (31 paths / 33 operations), source preserved in the merged contract.
- Extension: 10 read-only GET paths, 10 operations. Merged total **41 paths / 43 operations**.
- Added schemas: `DataSourceMeta`, `FeatureState`, `UIBootstrap`, `DashboardSummary`, `DisplayRecord`, `DisplayRecordList`, `AuditHistoryList`, `TaskAttemptSummary`, `TaskAttemptList`, `ResourceGenerationMeta`.
- Compatible optional additions to old schemas: `Resource.generation`, `Resource.lifecycle_state`, `Error.error.details_redacted`.
- Source-level static check: YAML can parse; operationIds unique; all referenced component schemas resolve; schemas use valid Draft 2020-12 constructs; old 31 paths and 33 operations deep-equal to original input; six synthetic JSON examples parse and five matching schemas validate.
- **Not verified:** OpenAPI official validator package / contract request–response live server tests / GLM FastAPI route coverage / PostgreSQL runtime. GLM must perform these before publishing a final `CONTRACT-LOCK.json`.
- Path namespace rule: `/api/v1/services/{id}` not added; UI service detail `/services/:id` uses `GET /api/v1/resources/{id}` filtered to kind `service`.
- `GET /api/v1/events` remains SSE; new `/api/v1/events/history` returns JSON.
- Source truthfulness: all new data-mode fields distinguish `LIVE`, `MOCK`, `UNAVAILABLE`; online status is not inferred by HTTP 200.
