# v3.0.1 Release Record (restored from Google Drive)

v3.0.1 was authored locally on 2026-11-11 on a local `v3.0.1` branch/tag
(commit `2fa330f744b56d47169b34230a078adc6618b654`, tree
`ced979dc77754eb75fb5e67ce2609e84d6ca1412`) and was never pushed to GitHub.
The only surviving copies of its delivery artifacts were six text files in
Google Drive. This directory restores those artifacts into the repository.

## Identity

- Baseline v3.0: commit `c0cf4ed09f31532b6d5fb9486f5b29e574325776`,
  tree `72684d6234b11643dd1d891def989ff3e6b944a0` (PR #7)
- Release v3.0.1: commit `2fa330f744b56d47169b34230a078adc6618b654`,
  tree `ced979dc77754eb75fb5e67ce2609e84d6ca1412`
- Contract: `3.0.0-fanout-local`, 89 paths / 106 operations,
  SHA-256 `28be05bbde88a55d3c97ce7ca1ebef70823be208d1ac216b36b70734f8625a6a`
  (unchanged since v3.0)

## Code fixes

Both v3.0.1 defect fixes are already absorbed into the `v3.0` branch HEAD
(`1dbc000a869e100963790bb4768bcd52127f96cd`, PR #8) in equivalent or
stronger form:

1. `CONTRACT_VERSION` in `backend/queries.py` is now derived from the single
   active contract (`CONTRACT["info"]["version"]`) instead of a literal.
2. `frontend/package.json` carries the `allowScripts` entries for
   `esbuild@0.28.2` and `msw@2.15.0`.

The incremental diff relative to v3.0 is preserved verbatim in
`patches/v3.0.1.patch` (2226 bytes, byte-identical to the Drive original;
SHA-256 `e164ba9e77e4dbf273ae05dc9dee02a51e2592b2caec589a9dc33b54cb66167e`;
verified with `git apply --check` against `c0cf4ed0`).

## Restored files

| File | Source (Drive) | Bytes |
|---|---|---|
| `docs/V3.0.1-START-HERE.md` | MagicWorkshop-v3.0.1-2fa330f7-START-HERE.md | 4810 (orig 4812) |
| `docs/V3.0.1-CHANGES-AND-KNOWN-ISSUES.md` | ...-CHANGES-AND-KNOWN-ISSUES.md | 5880 (exact) |
| `docs/V3.0.1-DEPLOYMENT.md` | ...-DEPLOYMENT.md | 6670 (exact) |
| `patches/v3.0.1.patch` | ...-PATCH.diff | 2226 (exact) |

START-HERE.md differs from the original by 2 bytes of whitespace inside the
package-structure code block; content is identical. The original artifacts
remain in Drive.

## Not restorable from Drive

The v3.0.1 package also contained `source.tar.gz` (349 files, 565204 bytes),
`deploy/magicworkshop-v3.service`, `deploy/magicworkshop-public.nginx.conf`,
`evidence/` files, and `VERSION.json`/`SHA256.json`. The binary archive and
these files were never uploaded to Drive as separate artifacts (only the six
text files above). The systemd unit and nginx configuration are reproduced
inline in `docs/V3.0.1-DEPLOYMENT.md`; the identity data is recorded here.
The full v3.0.1 source tree is reproducible as: v3.0 (`c0cf4ed0`) +
`patches/v3.0.1.patch`.

## Status

```
IMPLEMENTED=YES  TESTED=YES  DEPLOYED=YES(单机)  APPROVED=LOCAL_ONLY
PG_RUNTIME=NOT_RUN   GATE_B/C/D/E=未开
```
