# MagicWorkshop isolated backend · Local integration RC

Corrected independent copy of GLM RC f13d6e5. Original source ZIP SHA and scope are in docs/INTEGRATION-BASELINE.json. This copy is authorized for local code, synthetic data and loopback tests only. No PostgreSQL/Docker/production adapters are started.

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.lock
MWCP_PROBE_MODE=test .venv/bin/python -m pytest backend/tests tests -q
.venv/bin/python tools/route_coverage.py
.venv/bin/python tools/export_fixtures.py
```

For the whole UI/API demo, use the frontend repository's scripts/start-integration.mjs with this backend directory and MW_PYTHON set to the interpreter above. It generates independent in-memory Mock JWT material, starts the new API at 127.0.0.1:8127 and the same-origin session BFF at 8128, with the frontend at 5174. No credentials are copied from existing services. Raw Worker endpoints require a Worker token; the browser cannot reach them through the BFF.

All execution is a synthetic local.simulate/local-ledger task. It requires dry_run=true and a UUID Idempotency-Key, server-enforced MEDIUM approval, immutable request binding and resource generation. Worker claims are filtered by advertised/requested capabilities. Approval is consumed atomically with lease allocation. A lost approved task reconciles instead of being blindly requeued. Successful mock results have real in-memory bytes/digests in the Artifact registry; these are not private Drive downloads.

ResourceRec rejects public assignment. RegistryService mutations, controlled map insert/replace/delete and final probe commit use one reentrant lock. Generations advance even for ABA/delete-recreate; authority changes invalidate prior health observations. Only explicit test MockTransport probes are exercised. The production allowlist remains empty and DNS connection pinning is still a future gate.

The compatible 1.1.1 contract remains 41/43 and is shared byte-for-byte with the frontend. See contracts/CHANGELOG-1.1.1.md and docs/TEST-MIGRATIONS.md for the explicit compatibility and regression changes. Exported fixtures are schema-validated; tests do not mutate them.

Readiness intentionally returns 503/not_ready because real PG/probes are not connected. All state is process-local; restarting the API resets the ledger. Database DDL/repository material is a static proposal and contains a deliberately unimplemented PG adapter. No PG transaction, backup/restore, production OIDC/JTI persistence, real Worker or server capacity claim is made.

DEPLOYED=NO. APPROVED=LOCAL ONLY. Cherry and all legacy business, credentials, ports, reverse proxies and jobs remain frozen. Future production, real probes, PG runtime, credential rotation and external identity require their separate gates.
