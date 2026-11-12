# v3.0.1 historical release evidence

This record restores six text artifacts from Drive. It does not deploy a
service, recreate the original Git commit, or create a `v3.0.1` tag.
Use [the current US handoff](../../docs/US-PORTAL-INTEGRATION.md) and
[the GLM deployment gates](../../docs/GLM-DEPLOYMENT-HANDOFF.md).

## Reported identity and independently verified scope

The original author's VERSION.json reports commit
`2fa330f744b56d47169b34230a078adc6618b654` and tree
`ced979dc77754eb75fb5e67ce2609e84d6ca1412`, based on v3.0
`c0cf4ed09f31532b6d5fb9486f5b29e574325776` (PR #7).
Applying the archived patch to that baseline independently reproduces the
reported tree. The original commit object, authorship, parentage and local
branch/tag history were not recovered. Remote `v3.0.1` was absent when checked.
Do not manufacture that tag on the current, different source tree.

The contract remains `3.0.0-fanout-local`, 89 paths /106 operations, SHA-256
`28be05bbde88a55d3c97ce7ca1ebef70823be208d1ac216b36b70734f8625a6a`.
PR #8 (`1dbc000a869e100963790bb4768bcd52127f96cd`) already absorbed the valid
Bootstrap repair by deriving its version from the authoritative contract,
and retained explicit npm script approval. Do not apply the old patch again
to the integrated source. The original npm build-failure explanation was not
independently reproduced; the script policy is not proof of that diagnosis.

## Six exact originals

[drive-originals/MANIFEST.json](drive-originals/MANIFEST.json) records byte
sizes, SHA-256 values and Drive IDs. All six files were downloaded afresh;
five entries match the original SHA256.json. The catalog's own hash is recorded
separately. CI verifies these bytes and the duplicate patch.

| Original | Bytes | Scope |
|---|---:|---|
| [START-HERE.md](drive-originals/START-HERE.md) | 4812 | Exact; the earlier 4810-byte whitespace variant is replaced by a navigation wrapper |
| [DEPLOYMENT.md](drive-originals/DEPLOYMENT.md) | 6670 | Historical report, not the current US procedure |
| [CHANGES-AND-KNOWN-ISSUES.md](drive-originals/CHANGES-AND-KNOWN-ISSUES.md) | 5880 | Historical scope and claims |
| [PATCH.diff](drive-originals/PATCH.diff) | 2226 | Also unchanged at patches/v3.0.1.patch |
| [VERSION.json](drive-originals/VERSION.json) | 3420 | Available in Drive; restored |
| [SHA256.json](drive-originals/SHA256.json) | 1893 | Available in Drive; restored |

The prior assertion that VERSION.json and SHA256.json were unavailable was
incorrect. The original binary archive, source.tar.gz, actual systemd/nginx
files and raw runtime evidence still were not provided as standalone Drive
artifacts. Inline examples and metadata hashes do not replace those originals.

## Deployment assessment

`DEPLOYED=YES_LOCAL_ONLY`, 102.8MiB, public 401/200 and SSE results in the
originals are attributed reports, not this restoration's production evidence.
No PostgreSQL runtime, production identity, real Worker or US capacity gate
is opened by restoring the documents or passing CI.

The historical proxy rewrites Origin and fronts an unauthenticated synthetic
admin session issuer. Its oneshot service status does not supervise children.
Those examples must not be used to activate magicworkshop.fun. The current
US candidate keeps the browser read-only and requires a verified session BFF,
actual Origin validation, scoped paths, backup and rollback.

On 2026-11-12 anonymous GETs to the US site's workshop, build metadata and
API routes returned the same old AmazingWork HTML as `/`. This is externally
observed SPA fallback, not a working JSON API or a deployed new frontend.
Use `scripts/check_us_deployment.py` to fail on this condition. Passing that
GET-only smoke check still does not establish production readiness.

Status: historical evidence restored; source fixes retained; production
activation **not performed**; PostgreSQL runtime **not run**; deployment gates
remain blocked until the deployment owner validates them.
