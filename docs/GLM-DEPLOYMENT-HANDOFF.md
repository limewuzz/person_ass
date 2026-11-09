# MagicWorkshop → GLM deployment-engineering handoff

**Status: UNIFIED LOCAL RC; DEPLOYMENT_BLOCKED; DEPLOYED=NO.** This document transfers the integrated project and verification tools. It does not authorize or certify production or PostgreSQL runtime. GLM must obtain the user's separate Gate B authorization before isolated PG tests and separate authorization for production changes.

## 1. Repository, release identity and contract

Repository: https://github.com/limewuzz/person_ass . Target: `v0.1_personal`; integration branch: `integration/unified-magicworkshop`. Base: `5509483bb079763b6f8c0e2b4046d776452c7fd2` (merged PR #1). The unrelated `main` at `658e3f9193e4707e94547082841dc943c10db4d9` is not merged or modified.

The **exact final commit and tree** are recorded in `RELEASE-IDENTITY.json` inside the generated handoff directory, together with repository/target branch. They are generated from the actual clean Git HEAD, avoiding a self-referential hash in this source document. Read `git rev-parse HEAD HEAD^{tree}` after checkout and compare with that file. The final PR, CI run and post-merge identity are linked in the delivery record/Notion milestone.

Sole active definition: `contracts/openapi.yaml`, version `1.1.1-local-integrated`, **41 paths / 43 operations**, SHA-256 **e4194aa3d00dd1dca300010d7dc85e94b3d9da0a07a25c3fc977b092677cd1fa**. `contracts/CONTRACT-LOCK.json` and generated SDK match. `contracts/baseline` is historical evidence only. No interface semantics changed in unification.

## 2. Directory and service topology

```
frontend/                 React19 + TypeScript + Vite; accepted 22 templates
  integration/            local session BFF + synthetic worker + static host
  src/api/generated/      types/manifests generated from root contracts
  e2e/                    8 Mock browser cases
  integration/browser/    7 actual loopback browser cases
backend/                  FastAPI, auth, Registry, Tasks/Approvals/Worker
contracts/                authoritative OpenAPI/lock, schemas, fixtures
 dbpg/                    static migration/repository proposals (NOT RUN)
deploy/postgres/          historical role/Compose proposals (NOT RUN)
tests/                    backend contract tests
scripts/                  unified lifecycle, verification, scan and package
scripts/tests/            process ownership guard regressions
tools/                    route census and explicit fixture exporter
docs/                     original GLM history/security records + this handoff
```

Local dev: browser `127.0.0.1:5174` → Vite proxy → BFF `127.0.0.1:8128` → API `127.0.0.1:8127`. Local static candidate: browser `:5174` → minimal static host/proxy → same BFF/API. API+BFF and the local synthetic worker share one Python process. Browser never receives the API's bearer JWT. Worker claims only the new `local.simulate/local-ledger` tasks. External model gateways, old schedulers and cloud services are not connected.

## 3. Runtime and reproducible setup

Verified target is Linux x86_64; local host Debian13, CI Ubuntu24.04, Python3.12, Node24/npm11. Node and Python dependency versions are locked in `frontend/package-lock.json` and `backend/requirements.lock`. Frontend framework is unchanged. The necessary security updates are documented in DEPENDENCY-REVIEW.md. Chromium dependencies are development/test dependencies, not production control-plane residents.

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.lock
npm ci --prefix frontend
cd frontend
npx playwright install chromium
cd ..
node scripts/mw.mjs contract
node scripts/mw.mjs test
```

Use `MW_PYTHON=/absolute/path/to/venv/bin/python` when outside `.venv`. CI additionally installs browser system libraries on its disposable runner. No Docker/PG/service credentials are used. `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` avoids unrelated installed pytest plugins; tests do not require plugins. Finite static secret scanning and dependency audits run separately. The old private offline supplement targets the old dependency lock; use this repository's current lock, not that old cache, for the updated Vitest/PyJWT versions.

## 4. Frontend build and static serving

```sh
node scripts/mw.mjs build
node scripts/mw.mjs start --static
node scripts/mw.mjs stop
```

Build output is `frontend/dist/` in **loopback API mode**, without MSW success fallback. `build-meta.json` binds it to the current HEAD and contract. Root test runs the 7 loopback E2E against these built assets; 8 separate Mock E2E remain in development/MSW mode. SPA paths fall back to index.html, assets and V1/Prism history retain original paths. Static responses apply Content-Type/nosniff. In production GLM should serve these assets using an approved lightweight TLS/static/proxy arrangement after identity/origin review; the included Node static host is a loopback candidate, not a production web/TLS service. Model inference, headless browsers and heavy workers stay off the US controller.

## 5. API/BFF commands and local lifecycle

Full developer start: `node scripts/mw.mjs start`; stop: `node scripts/mw.mjs stop`. Start backgrounds a supervisor; only its process group may be stopped. State records PID, Linux process-start ticks, repository and a nonce. Stop refuses reused/foreign PIDs. Port occupancy is checked before new service launch; nothing existing is killed. Startup readiness is accepted only after the launcher's ownership proof, not merely an HTTP200 on an existing port.

Foreground API/BFF (synthetic identity only): `.venv/bin/python frontend/integration/local_stack.py --backend backend`. It binds API8127/BFF8128; start a static host or Vite5174 separately with the same Origin to use it. The full launcher is preferred because it reserves/checks all ports first. A standalone raw API can be run for future approved adapter work with `.venv/bin/python -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8127 --no-access-log`; this requires appropriate synthetic auth setup and does not create a BFF or synthetic worker. The accepted local demo generates its issuer material in memory and ignores inherited production auth files.

**Do not use legacy `backend/Dockerfile.api` or `backend/entrypoint.sh` as ready deployment recipes.** They are preserved historical proposals with old module-copy/contract-layout and secret requirements. They have not been built or run here; GLM must replace/review them as part of the later deployment gate. Compose `.proposal` files also remain unexecuted proposals.

## 6. Environment and identity boundaries

`deploy/local.env.example` contains placeholders only. Local startup uses `MW_PYTHON`, optional `MW_INTEGRATION_REPORT`, and internal ephemeral test configuration. Never copy existing credentials into it. The local launcher sets test probe mode and a local issuer internally; external real-probe allowlists stay empty.

The local cookie is HttpOnly/SameSite=Strict, server-side JWT is renewed, POST validates exact Origin and memory CSRF, and browser Worker URLs are denied. The cookie is not a production Secure/TLS session; WEB_ORIGIN is the local5174 origin. Production OIDC, HTTPS, session lifecycle/revocation, durable JTI and authorization configuration must be designed and verified before changing origins or binding publicly. Never put bearer tokens into URL/localStorage. Local demo flags cannot grant production rights. An exposed PAT is considered unusable; user revocation remains an owner action, and this integration never uses that PAT.

## 7. Communication, health and logs

All new listeners use127.0.0.1 only: 5173 standalone MSW; 5174 full UI/static; 8128 BFF; 8127 API. No legacy ports are probed. Browser fetches only the new same-origin API; actual-loopback E2E checks absence of remote browser requests and service workers.

`GET /api/v1/health/live` returns200 with honest timestamp. `GET /api/v1/health/ready` returns **503/not_ready**, including database not_connected and unavailable dependencies. A local RC test explicitly expects that503. Do not make readiness200 to pass deployment checks while PG/production identity is missing.

Local supervisor log: `.runtime/local.log`; ownership state: `.runtime/local.json`; both ignored. API/BFF disable access logs and do not print tokens. Tests: `frontend/evidence/release/` and separate Mock/live JUnit/report locations. HTTP evidence contains method, contract path, status and schema result, no headers or credentials. Vite watch ignores evidence, Playwright reports, test-results and runtime directories. In later approved operations choose bounded structured logs with rotation and redaction; no Loki/Prometheus stack is assumed.

## 8. Database state, migration order, roles and backups

`dbpg/repository.py` contains protocol/blueprint methods raising **NotImplementedError("PG_RUNTIME NOT RUN")**. Current TaskEngine/Registry/session/JTI state is in process memory. **There is no PostgreSQL runtime connection, persistent task repository or tested restart recovery.** Local restart intentionally loses the ledger.

Static materials: `dbpg/migrations/0001_init.sql` (schema, constraints, resource generation, outbox) and `deploy/postgres/` (role/init/permission proposals). After separate Gate B approval, GLM must implement a real repository and transaction boundaries, verify its schema matches actual task/approval/lease semantics, and review the proposals before any execution. Proposed sequence: isolated disposable cluster/volume and loopback isolation → approved secret files/least-privilege role setup → migration as migration role → app role negative-permission checks → repository integration → CAS/uniqueness/approval consumption/outbox/generation concurrency → crash/restart persistence → encrypted backup/restore into a fresh volume. No migration is auto-applied by this project.

Do not reuse production users, schemas, credentials or volumes. App role must not be superuser or own migration powers; worker/browser roles must not bypass the API. Define backup ownership, encryption key storage, retention, restore verification and migration rollback/forward procedures before production. A tar of source or the current memory ledger is not a database backup.

## 9. Candidate start/stop/upgrade/rollback SOP

For local RC: verify Git HEAD and contract against RELEASE-IDENTITY; install exact locks; run contract/full tests; build; start; check live200/ready503 and marked LOCAL MOCK; stop only this supervisor. Use `node scripts/mw.mjs package` from the exact clean tested commit to produce source/static/evidence ZIPs, handoff, identity and SHA256SUMS. Restore source into a fresh directory, install locks and repeat tests. Rebuilds are source/test reproducibility checks, not byte-for-byte identical toolchain promises.

For later approved deployment: GLM should prepare versioned immutable release directories, explicit approved service definitions, least-privilege users and loopback bindings, run readiness/synthetic acceptance before switching a proxy, record the previous release and database migration state, and upgrade without modifying old business. These are **candidate procedures only**. Rollback requires both compatible application and database schema/restore plan; do not downgrade code against incompatible migrated storage. Any real switch/restart/network change needs the deployment approval. Local code rollback can check out a previous release in a new worktree; it cannot recover lost in-memory task state.

## 10. Permissions, network and resource planning

Single user, one write controller, Mac stays read-only standby/local Worker; no automatic promotion on US disconnect. Offline UI uses cached read-only data and reconciles after recovery. Server enforces approval policy, idempotency, lease/generation CAS and late-result rejection, independently of UI flags. Registry authority writes and probe commit share the single-process lock; this is not proof of a multi-process PG linearization protocol.

Planning target: US server6 cores/about11GiB RAM; new lightweight control plane about1.5GiB, initially reserve about2GiB. This is not a measured deployment capacity result. Record real API/BFF/PG/static/proxy RSS/PSS, CPU, disk/IO, peak concurrency, restart and OOM behavior in Gate B, including old-business headroom. Prefer static frontend and a bounded database pool; do not add Redis/Loki/Prometheus/Kubernetes by default. Inference/browser automation/heavy workers belong elsewhere. Local test RSS excludes real PG, existing US workloads and deployment proxy.

No access or changes to Cherry Studio (including its code/API/models/config/sessions/auth), Rakazo,8765, existing DB/proxy/cron, US business, Tencent or UCloud legacy business, real probes/workers, credential rotation or production network. Cherry may only retain already-approved static links; no iframe/proxy/prefetch.

## 11. Blocking deployment gates

| Gate | Current state / required GLM evidence |
|---|---|
| PG repository + migration runtime | **BLOCKED**: implement adapter, isolated migration/role tests |
| Transaction/CAS/persistence | **BLOCKED**: task idempotency, approval-once, leases, generation, outbox under concurrent PG transactions |
| Restart/backup/restore | **BLOCKED**: crash/restart, fresh-volume encrypted restore and recovery objectives |
| Production identity/TLS | **BLOCKED**: OIDC/JTI/session/CSRF/Origin/Secure cookie and TLS/reverse-proxy review |
| Real Worker/probes | **BLOCKED**: explicit capability policy, target allowlist, DNS pinning/SSRF and connection/concurrency budgets |
| US capacity and legacy isolation | **BLOCKED**: approved sandbox measurements,1.5–2GiB budget and old-service isolation |
| Credential incident | **OPEN**: owner revokes exposed PAT; rotation is not executed here |
| Production deployment | **NOT RUN** until explicit deployment approval and gates pass |

## 12. GLM verification commands and acceptance table

```sh
git status --porcelain
git rev-parse HEAD HEAD^{tree}
node scripts/mw.mjs contract
node scripts/mw.mjs security
node scripts/mw.mjs test
node scripts/mw.mjs build
node scripts/mw.mjs start --static
node scripts/mw.mjs stop
node scripts/mw.mjs package
# Optional separate audit interpreter after installing pip-audit==2.10.1:
MW_AUDIT_PYTHON=/absolute/path/to/audit-venv/bin/python node scripts/mw.mjs dependencies
```

| Local acceptance | Expected evidence |
|---|---|
| Backend inherited baseline | 167/167 normal and reverse, zero unexpected skips |
| BFF | 5/5; HttpOnly/SameSite/Origin/CSRF/schema/Worker denial |
| Supervisor guard | 3/3; foreign PID/start-time mismatch and stale state |
| Frontend | 17 unit/contract, typecheck/lint/build |
| Browsers | 8 Mock +7 real-loopback/static;22 templates at1600/1280/768/390 |
| Scenarios | success/failure/reject/expired approval; lease expiry/late finish;100-way idempotency;disconnect/read-only/recovery/reconciliation |
| Contract | 41/43, exact frozen SHA; root-only active OAS; regenerated SDK diff empty |
| History and safety | no old GLM doc deletion, V1/Prism hashes unchanged, finite scan and dependency audits, no real network/PG/deployment |
| Source identity | clean HEAD/tree bound to JUnit/CI/package manifest; ordinary PR merge into v0.1_personal |

CI artifacts retain current-commit logs/JUnit and necessary redacted screenshots. Full screenshot inventories are included in the handoff validation ZIP; test reports remain ignored. GitHub CI and final PR links are recorded in the release delivery, not inferred from local success.

## 13. Transfer decision

Codex delivers unified source, repeatable local tests, CI and a deployment preparation package. GLM receives a **DEPLOYMENT_BLOCKED** system with an accepted local simulation loop. Gate B and production operations belong to GLM only after the user's separate authorization. No pending production gate is silently marked completed by this handoff.
