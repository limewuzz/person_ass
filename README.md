# MagicWorkshop · V3 single-input fan-out local RC

One intent creates one WorkItem, one aggregate approval and independently leased Outbox branches. Four recipe cards, signed webhook ingress and a crash-aware Mac relay extend the existing workspace; see [V3 architecture and adapter limits](docs/V3-FANOUT.md).

Single-user control plane with the accepted React/Vite frontend and FastAPI backend in one repository. **LOCAL RC only; DEPLOYMENT_BLOCKED.** The GLM Phase A PostgreSQL code is retained; runtime behavior and production deployment are not validated by this local release.

Target branch: `v3.0`, based on merged v2.0.1 `c17b64b`. The independent `main` branch is unchanged. Architecture, commands and remaining production gates: [GLM deployment handoff](docs/GLM-DEPLOYMENT-HANDOFF.md). Source provenance: [frontend import](docs/FRONTEND-PROVENANCE.md).

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.lock
npm ci --prefix frontend
cd frontend
npx playwright install chromium
cd ..
node scripts/mw.mjs start            # local API + BFF + Vite, background, 127.0.0.1 only
node scripts/mw.mjs stop             # signal only the recorded owned process group
node scripts/mw.mjs contract         # root OpenAPI → SDK, drift and route checks
node scripts/mw.mjs test             # clean Git required; full local RC including static-build E2E
node scripts/mw.mjs build            # frontend/dist, loopback API mode, no MSW fallback
node scripts/mw.mjs start --static   # serve that build through the same session BFF
node scripts/mw.mjs stop
node scripts/mw.mjs package          # exact-HEAD source/static/evidence + GLM handoff in release/
```

Open http://127.0.0.1:5174 for the user workspace and `/workbench/fanout` for the V3 recipe console. The administrator console is `/dashboard`, and the retained Motion homepage is `/architecture`. See [user-workspace release](docs/USER-WORKSPACE-RELEASE.md) for the supported task/approval/results flow, recovery behavior, local V2 conversations/uploads/sync and unavailable live model execution and `/app/` build instructions. Ports 5174/8127/8128 must be free; the launcher refuses to reuse or stop existing services. Logs and owner state: `.runtime/`; validation: `frontend/evidence/`. For Python outside `.venv`, set `MW_PYTHON` to its interpreter. Pure MSW frontend demo: `npm --prefix frontend run dev` (5173).

`contracts/openapi.yaml` is the sole active contract: 3.0.0-fanout-local, 89 paths / 106 operations, SHA `28be05bbde88a55d3c97ce7ca1ebef70823be208d1ac216b36b70734f8625a6a`. Historical `contracts/baseline` is reference evidence. Frontend SDK and BFF consume the root file; no active frontend copy exists.

The 22 accepted templates and V1/Prism bytes are retained. Legacy `local.simulate` still requires server-enforced MEDIUM approval. V3 defaults to SIMULATE; LIVE additionally requires server grants bound to owner/recipe/target/worker and an explicitly enabled adapter. AI/knowledge, WeChat sending, Colab execution and implementation adapters remain unavailable; Notion/Drive/GitHub/Reminders adapters are unverified candidates. A synthetic worker operates the new in-memory ledger; restart loses state. Unknown external sources remain UNKNOWN/UNAVAILABLE. Local session identity, cookie flags and JWT issuer are not production OIDC/TLS.

CI runs backend tests in both orders, route/runtime schema checks, BFF security, ownership guards, TypeScript/lint/Vitest, shared SDK generation, production frontend build, original and new user-workspace Mock/static-loopback browser cases plus a separately rebuilt `/app/` deployment check, finite secret scan and dependency audits. Actions use read-only contents permissions and no service credentials or PG. Source must stay clean. Reports do not trigger Vite reloads.

No Cherry Studio, Rakazo, 8765, existing databases, reverse proxies, cron or server business is accessed. PG, persistent transactions/recovery, production identities/TLS, real workers/probes, credential rotation and US capacity/isolation remain separate gates for GLM after user authorization. Legacy Docker/Postgres files are historical proposals, not deployable production instructions.

HTTPS session deployment candidate: [build, authentication gate and scoped rollback](docs/SESSION-DEPLOYMENT.md). This requires the existing server identity boundary and an authorized deployment channel; the local issuer is never a production fallback.

Current V2 repairs and isolated PostgreSQL execution boundaries: [Gate B V2 handoff](docs/GATE-B-V2-EXECUTION.md). PostgreSQL runtime and production deployment remain NOT_RUN.
