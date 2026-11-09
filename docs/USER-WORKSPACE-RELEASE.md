# User workspace release — local integration and GLM handoff

Status: **IMPLEMENTED; local validation required on the final clean commit; NOT DEPLOYED BY THIS CHANGE.** The current public deployment is outside this change. Its identity, proxy configuration and authentication must be verified by its deployment owner before accepting this release for production.

## Product entry and retained pages

The root `/` is now the personal workspace, with a warm, quiet layout and a top navigation, rather than an infrastructure sidebar. `/workbench` is an alias. The existing Spectra Motion architecture homepage moves to `/architecture`; all 15 administrative pages, four detail templates and both V1/Prism history files remain. The accepted history bytes are checked by `scripts/check_baseline.py`.

| User route | Behavior | Frozen API |
|---|---|---|
| `/` or `/workbench` | Enter up to 200 characters; choose task, idea or paper; review scope before submitting; recover a session draft | bootstrap, capabilities, work-items POST; tasks POST only for task kind |
| `/workbench/history` | Search titles/task IDs, filter status, sort date; saved ideas/notes are separate from execution | paginated work-items and tasks |
| `/workbench/tasks/:id` | Human-readable state, pending authorization, cancellation, attempts, events and result metadata; export a JSON task record | tasks/id, events, attempts, approvals, artifacts; existing approve/reject/cancel POST |
| `/workbench/results` | Search registered artifact metadata; return to source task | artifacts, tasks, work-items |
| `/workbench/assistants` | Display actual authorized agent directory and capability status | agents, capabilities |
| `/dashboard` and other old routes | Existing administrator console | unchanged existing mappings |

There are **27 page templates**: the accepted 22 plus five user templates. The workbench alias is not a separate template. All layouts target 1600/1280/768/390, keyboard focus and reduced motion. Product creation/authorization controls use plain language and explicit local-simulation scope. Current MOCK/UNKNOWN/UNAVAILABLE indicators are never upgraded to LIVE by presentation code.

## What works and what is unavailable

A task creates a WorkItem, then the existing `local.simulate` task on `local-ledger`, with `dry_run=true`, `arguments={outcome}` and a stable `Idempotency-Key`. The server decides policy and creates MEDIUM approval; a user may approve/reject in the same task page. Only the separately running synthetic worker can claim/finish. Browser code never receives a worker token or calls Worker endpoints. Ideas and paper notes save a WorkItem without task dispatch.

The current API has no free-form model invocation, agent assignment, file upload/content download or conversation operations. Those controls are explicitly unavailable. Agent cards are not a claim of model availability. Artifact URIs render as text; no iframe, proxy, automatic download or prefetch occurs. “Export task record” creates a JSON file from authorized, already-read metadata; it is not a real artifact download. See `WORKSPACE-CONTRACT-REQUEST.md` for the separate backend-owner change proposal.

## Submission consistency and privacy

- Unsaved drafts use `sessionStorage` for the current browser session, with an explicit product label. No auth token is stored. Refusing storage disables submission rather than losing recovery state.
- The immutable submission journal is persisted before the first write. The task payload/key survive response loss and page reload. Repeating task submission uses the same key and work item.
- WorkItem POST has no idempotency guarantee in the locked contract. An unknown response blocks replay and asks the user to inspect history. Clearing the local journal requires a confirmation that explains it does not cancel server work. No silent automatic WorkItem retry occurs.
- Related approvals/artifacts/work items follow all cursors before joins. A cycle, later-page error or the explicit 20,000-record safety limit yields an error, not a misleading empty/success result.
- Polling is limited to visible active task details and stops at terminal/reconciliation states. Background polling is disabled. Network loss disables writes, retains authorized cache, and displays a read-only banner. On 401/403/404, private task/detail data is hidden even if a prior successful response is cached.
- HIGH/CRITICAL, expired or non-pending approval is not actionable in the UI. The server remains authoritative; a race returns its declared error, never a fabricated success.

## Authentication and contract corrections

The local BFF already required a session for private GET/SSE. New checks also reject non-loopback peers and unexpected Host values, including requests attempting to mint a local admin session with a forged Origin. Error and private responses use no-store; local static/API responses set nosniff/frame/referrer safeguards, and the static application has a CSP. Historical HTML keeps its original inline scripts and a separately constrained inline-compatible policy. HTTPS/HSTS and production identity are not implemented by this local host.

These guards intentionally make the local issuer unusable behind a public Host. **Do not remove these checks to deploy.** Build a production identity/session boundary reviewed by the deployment owner. Raw backend anonymous requests also have explicit GET/SSE regression tests. This is not evidence that the current remote proxy/session implementation has been fixed.

`GET /api/v1/events/history` now enforces the existing `limit=25`, range 1–100 definition, correcting implementation drift; the shared OpenAPI and generated SDK remain byte-identical. No new active contract or guessed endpoint was added.

## Prefix and static serving

For normal loopback development:

```sh
node scripts/mw.mjs start
# http://127.0.0.1:5174/
node scripts/mw.mjs stop
```

For a root static candidate:

```sh
node scripts/mw.mjs build
node scripts/mw.mjs start --static
node scripts/mw.mjs stop
```

For an `/app/` static candidate:

```sh
MW_WEB_BASE=/app/ node scripts/mw.mjs build
node scripts/mw.mjs start --static
# http://127.0.0.1:5174/app/
node scripts/mw.mjs stop
```

The build embeds `web_base` in build-meta.json. Vite asset base, React basename, history links and the owned static server all use that prefix. `/app` redirects to `/app/`; direct entity routes (including dotted IDs) and reloads use the SPA fallback. Missing assets remain 404. API and local-session routes stay at the same origin's root. An approved production static/proxy configuration must reproduce that mapping, preserve authentication on JSON/SSE, and redirect login to the actual frontend prefix. The supplied Node host binds only 127.0.0.1 and is not production software.

## Reproduction and evidence

```sh
node scripts/mw.mjs contract
node scripts/mw.mjs security
node scripts/mw.mjs test
node scripts/mw.mjs package
```

The complete runner retains original tests, adds user-workspace cases in Mock and actual loopback modes, includes the latest GLM offline dbpg suite, and separately rebuilds/tests `/app/` then restores the root build. No PG container/database or production network is needed. Prefix verification refuses occupied ports through the existing owned launcher and stops only its own child. The CI has minimum contents:read permissions; JUnit and synthetic screenshots are artifacts.

Evidence: `frontend/evidence/release/integrated-release.json`, per-step logs and JUnit; workspace screenshots under `frontend/evidence/workspace/`; prefix JUnit/screenshots under `frontend/evidence/prefix/`. Packaging binds source/static assets/evidence to the exact clean HEAD/tree and frozen contract SHA. Final test counts, CI URL and source identity belong to the delivered release record, not to historical baseline numbers in older handoffs.

## Deployment blockers

This release does not authorize or perform production rollout, server access or credential rotation. The latest GLM Phase A PostgreSQL repository/migration implementation is preserved and tested offline; runtime wiring, transaction/CAS/persistence, restart recovery and backup restore are **not verified here**. Production identity/session validation, TLS/proxy isolation, real worker/probe policies, resource budgets and old-business isolation remain deployment-owner gates. Current public-service authentication must be independently rechecked after any owner-applied changes.

The original 1.5 GiB target / 2 GiB reserve is still a planning budget. The workspace adds no server, queue, database, inference worker or background telemetry service. No Cherry/old-business API is contacted. Cherry remains frozen and artifact links do not trigger external requests.
