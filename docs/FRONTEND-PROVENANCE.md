# Frontend source provenance and import

Accepted source HEAD: `d23732aeac5c27c0dc782e2f5720e778d3308158`.
Accepted tree: `e397c78c7ac59b4db258c28d55ca0199ae6a83fb`.
Source bundle Drive: https://drive.google.com/file/d/1pYjdor_PrNg9oW5rIegy999JcoA1SkyX/view (tools ZIP contains frontend.bundle).
Original source ZIP: https://drive.google.com/file/d/192XZ_F6i_2TrDXB0d_2V0RkHQNZ2z9uu/view ; ZIP SHA `72d242f997defd15f32e53b024a7b1b872c66cce2305142c34eaf3520641930c`.
Bundle SHA is pinned in UNIFIED-BASELINE.json. The verified Drive-recovered bundle was cloned; HEAD, complete tree and clean source matched, then `git archive` imported all 85 tracked files into frontend/. Every imported file matched before integration edits.

The backend parent is actual GitHub branch v0.1_personal at 5509483bb079763b6f8c0e2b4046d776452c7fd2, containing the GLM history and PR #1. The frontend tree is imported as source, with original IDs recorded here; no unrelated main history is merged and no parentage is invented. Existing backend docs, security incident records, contracts, dbpg, deploy and tests are retained. The prior root README is preserved in docs/archive/GLM-BACKEND-README-before-unification.md.

Integration edits are limited to root contract paths, startup/verifier entry points, report watch exclusions, static candidate serving, documentation and dependency fixes. The two frontend active contract copies are removed; SDK, BFF and audit read ../contracts at the root. Browser routes, feature assertions, API semantics and historical pages are retained. Service detail still reads resources/{id}; SSE events and JSON events/history stay separate.

Dependency audit required Vitest 3.2.7→4.1.12 (removes vulnerable tinypool and fixes mocker advisories), typescript-eslint 8.72.1 (resolved version unchanged, now pinned), a scoped minimatch 11.0.1 override for the parser advisory, and backend PyJWT 2.13.0→2.15.1. No application framework or frozen OpenAPI semantics are changed. Exact results and remaining advisory status are in DEPENDENCY-REVIEW.md; all original test assertions remain.

Historical HTML fingerprints are independently checked on every contract/build verification:

| Resource | Bytes | SHA-256 |
|---|---:|---|
| frontend/public/versions/v1.0/index.html | 35476 | 7fc6bbc75391b43afec7d2414c5079f9ea743574b38f9661e1d6795b52496655 |
| frontend/public/versions/v2.0-prism/index.html | 59796 | 5865ecfc6842b1faa012ddfea466321a504b10f1d8beb845c1d243247fb0cf94 |

`UNIFIED-BASELINE.json` lists every original backend path. Review the PR diff to confirm no baseline deletion; historical documents retain their original bytes. The only active contract SHA remains e4194aa3d00dd1dca300010d7dc85e94b3d9da0a07a25c3fc977b092677cd1fa (41/43). Git history and the published PR provide the final source identity; deployment packages include RELEASE-IDENTITY.json generated from the actual clean HEAD and tree.
