# Regression migration record

Original GLM baseline 156 tests passed unchanged in the earlier independent run. Its original ZIP and Python source remain intact in /workspace/glm-rc and the original Drive artifact.

The corrected branch keeps all 156 named cases and adds integration/security regressions. Changed test assumptions are explicit:

- test_r10_gpt6_repro / test_r9_gpt6_repro / test_r5_regression: fixture owner/node transfers now call RegistryService. Field assignment is rejected. A transfer clears the prior authority's health evidence to UNKNOWN; the old expectation that stale HEALTHY survives an owner transfer is corrected.
- test_r11_gpt6_repro: a public direct write is rejected; a real controlled writer blocks while the final commit holds the shared lock, then advances generation and clears old health. The ABA case uses two real controlled transitions and still rejects the old observation.
- test_registry_service: snapshot immutability remains asserted; rejected raw writes plus controlled ABA generation/write revision advancement are checked.
- test_workergw: lease/CAS cases now declare probe.http.get in the worker heartbeat. Empty advertised capability lists no longer authorize arbitrary tasks.
- test_queries_rc: assertions now follow the originally promised enums and response envelopes; the actual 1.1.1 compatible revision adds readiness 503 and optional context. Simulation requires an explicit local capability, resource, dry_run and Idempotency-Key header. Caller risk/requires_approval cannot weaken server policy. Snapshot export tests write to tmp_path; explicit export is tools/export_fixtures.py.
- tests/test_contracts: SHA is updated to the recorded compatible revision. Baseline YAML/lock bytes are archived under contracts/baseline; 41 paths and 43 operations stay fixed.

No failing assertion was removed to pass a count. The old final-read race is independently reproduced as failed against the original package. New tests verify that an untrusted direct writer is rejected at that exact window and an authorized writer serializes with the commit. All 43 HTTP operations validate actual responses against shared YAML, including UUID/date formats, status codes and dependency 503.
