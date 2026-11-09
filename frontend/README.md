# MagicWorkshop frontend

Imported from accepted HEAD d23732aeac5c27c0dc782e2f5720e778d3308158, tree e397c78c7ac59b4db258c28d55ca0199ae6a83fb. See ../docs/FRONTEND-PROVENANCE.md for import checks and directory changes.

All 22 templates, responsive 1600/1280/768/390, keyboard/reduced-motion and historical V1/Prism resources are preserved. React/TypeScript/Vite/TanStack Query/MSW remain the application stack. Root ../contracts/openapi.yaml is authoritative. `npm run generate` consumes it directly.

Use the repository root README and scripts/mw.mjs for full startup/stop/test/build/package commands. `npm run dev` here remains the standalone, clearly labelled local MSW demo at 127.0.0.1:5173. `npm run e2e` covers that mode; the root test command additionally runs the 7 real-loopback E2E against the built static application. The new local identity, BFF and synthetic Worker never connect to legacy services.

Archived handoff/PRD/review documents under docs/ record the original two-repository RC; current operation and deployment gates are at ../docs/GLM-DEPLOYMENT-HANDOFF.md. The frontend scripts/verify-* entry points delegate to the unified verifier.
