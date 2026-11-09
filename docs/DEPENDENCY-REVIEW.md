# Dependency review · unified RC

The frozen API and application framework are unchanged. Baseline dependency scans were executed before publishing the unified feature branch. The current lockfiles were re-audited with npm audit and pip-audit2.10.1; **zero known npm or Python advisories** were returned at review time. This is a dated advisory-database check, not a future vulnerability guarantee; CI repeats it.

Necessary changes:

- Vitest3.2.7→4.1.12 fixes the mocker issues GHSA-82fw-gwwq-j7x9 / GHSA-qxg6-89mg-rqv8 and removes the vulnerable tinypool dependency (GHSA-5gmw-xhrv-c9v3 / GHSA-85c8-ppgw-ccpr). Existing17 test cases and assertions are retained.
- typescript-eslint resolved8.72.1 stays unchanged and is now an exact direct pin. Its typescript-estree minimatch dependency has a scoped override to11.0.1 for GHSA-g3hv-75wg-m249. That version retains require/import exports and supports the chosen Node24. Typecheck, parser/lint and all frontend regressions must pass; no blanket transitive override or advisory ignore is used.
- PyJWT2.13.0→2.15.1 fixes the reported registered-claim/header/validation advisories. There were15 baseline audit entries for2.13.0, including GHSA-pxh4-856f-4h89 and PYSEC-2026-4146; current2.15.1 is not reported affected. No vulnerability IDs are ignored. Auth behavior remains constrained by existing algorithm/issuer/audience/expiry/scope tests and the complete backend suite.

Python runtime lock is backend/requirements.lock; frontend lock is frontend/package-lock.json. No dependency was updated with npm audit fix --force, no test assertion was weakened, and no production credential or external service was used. Scoped test dependency changes are recorded in the PR, while original source provenance remains in FRONTEND-PROVENANCE.md.

CI: npm audit --audit-level=high plus python -m pip_audit -r backend/requirements.lock --strict. It uses read-only repository permissions. It retains JSON audit outputs; production runtime is not started. Local command: MW_AUDIT_PYTHON=/path/to/isolated/audit-venv/bin/python node scripts/mw.mjs dependencies after installing pip-audit==2.10.1 there.
