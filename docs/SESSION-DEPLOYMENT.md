# HTTPS session deployment candidate

The user has authorized deploying the new personal workspace. This change prepares a static candidate; **it does not claim a production deployment, production authentication fix or PG runtime acceptance**. The existing loopback issuer/static host remain development-only and must not be bound publicly or copied in as a production identity provider.

## Build and runtime modes

`mock` and `loopback` require a loopback frontend origin. Unknown modes fail closed rather than silently becoming Mock. A `session` build requires an explicit HTTPS origin matching the actual frontend origin; a loopback override is forbidden.

```sh
MW_PUBLIC_ORIGIN=https://cp.magicworkshop.site MW_WEB_BASE=/app/ node scripts/mw.mjs build-session
```

The result is `frontend/dist`, with source identity, public origin, base path, `mode=session`, `read_only=true` and the unchanged contract SHA in build-meta.json. The existing login root redirects to `/app/`. React routes, assets and historical links use that base. No backend, database, proxy or running service is changed by the build.

The browser verifies the existing HttpOnly cookie session through the frozen `GET /api/v1/me` before mounting the workspace. A 401/403 does not mint a local actor, register MSW or expose a cached task. Only same-origin HTTPS API and SSE URLs are used. Server authentication must be independently tested: receiving a 200 from a misconfigured public API is not proof that a session is valid.

Session candidates start read-only, including old administrative task/approval/cancel controls. The API client also refuses mutation calls, even if a disabled UI control is bypassed. `MW_SESSION_WRITES=enabled` is an explicit later build option; it is not a server authorization mechanism. Do not enable it before the deployment owner has verified server session/role/object/CSRF/Origin/Worker boundaries and the intended backend execution/persistence mode. Existing UI task gates still require LOCAL_MOCK/MOCK_ONLY; this change does not add a production executor or new business API.

When writes are explicitly enabled, the client uses the existing login's `mwcp_csrf` storage value with `X-MW-CSRF`, and refuses missing/invalid values. It never stores or supplies a bearer/worker token. Production session issuance, revocation, password validation and TLS remain server responsibilities; the frontend does not create or migrate accounts.

## Non-mutating release gate

```sh
python scripts/verify_public_boundary.py --origin https://cp.magicworkshop.site --output /absolute/private/path/public-boundary.json
```

This makes five bounded GETs without Cookie or Authorization, closes responses without reading bodies, follows no redirects and requires 401 for me/tasks/nodes/audit/SSE. A 200 or unexpected status is BLOCKED. The gate does not request tasks, change data or trigger probes. A successful anonymous gate must be supplemented with a valid-cookie 200 test, expired/invalid-cookie denial, no-store checks and same-origin login/SSE tests. A login page alone cannot protect a separately exposed API path.

The existing public deployment's private observations and access/transport evidence stay outside Git. No server credential is part of this repository, build or gate script.

## Deployment sequence after server access is available

1. Inspect only the new control-plane frontend/service/vhost. Record current asset directory, active configuration, upstream mapping, source commit and permitted listener. Do not infer these paths from a local layout or inspect other business authentication/configuration.
2. Back up the current new-control-plane static release and its own vhost/service files with restrictive permissions; record SHA and the prior target. Do not replace the production backend with `frontend/integration/local_stack.py`.
3. Resolve any anonymous API exposure in that service's existing session/proxy boundary; verify the anonymous gate and valid/invalid-cookie behavior before publishing the new UI. No fixed admin bearer may be exposed through an unauthenticated location.
4. Build and hash the session candidate from a clean, tested commit. Upload it to a new versioned release directory; keep the previous release. Prepare a narrowly scoped change to the existing new-control-plane vhost's `/app/` fallback/assets mapping. Preserve every other vhost and database/Worker/probe configuration.
5. Validate configuration, atomically switch the frontend release, and use the service's ordinary reload procedure. Do not restart all containers or modify global routing/DNS. Verify build-meta, login landing, direct navigation/reload, all 27 templates, both historical pages, cookie headers, private API/SSE authorization and unchanged source truth labels. Keep readiness 503 if the backend reports unavailable dependencies.
6. If any gate fails, restore the previous static target and only the changed new-control-plane configuration, validate/reload, and record the failure. Database downgrade/migration, real execution, credential rotation and old-business actions are outside this frontend rollout.

The actual commands, paths, backup identity and rollback diff must be filled from the inspected server, not guessed. SSH transport availability is independent of having a password. Use an already working authorized local workspace/proxy or configured VPN, without weakening host-key verification or placing credentials in code/logs.

## Verification and evidence

`node scripts/mw.mjs test` preserves all prior local checks and adds HTTPS-session browser cases. `frontend/scripts/check-session.mjs` separately builds for reserved `https://workspace.test`, intercepts all requests locally, tests unauthenticated denial, cookie-only startup, read-only UI, session expiry, zero local-session POSTs and zero MSW registration, then restores the loopback build. These are synthetic HTTPS-origin browser tests, **not** real TLS/server authentication validation. Four configuration tests cover mode fallback, public-origin mismatch and read-only defaults. Production observations never count as simulated test success.

Reports: `frontend/evidence/session/junit.xml`; full clean-commit logs and JUnit remain under `frontend/evidence/release/`. The shared backend contract is unchanged: 1.1.1-local-integrated, 41 paths/43 operations, SHA e4194aa3d00dd1dca300010d7dc85e94b3d9da0a07a25c3fc977b092677cd1fa.
