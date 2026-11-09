# Backend-owner contract request: production user workflows

Status: **PROPOSAL ONLY; NOT AN ACTIVE CONTRACT.** Owner: GLM/backend. The frozen 1.1.1-local-integrated OpenAPI stays 41 paths/43 operations, SHA e4194aa3d00dd1dca300010d7dc85e94b3d9da0a07a25c3fc977b092677cd1fa. The frontend delivered here only calls that contract. This request is required before the user workspace can claim real model conversation, attachments or file-content download.

| Need | Current limitation | Required design and acceptance |
|---|---|---|
| Natural language work | WorkItem contains a 200-character title; Task only implements local.simulate/outcome | Versioned request/body schema for user instructions, capability dispatch and agent selection; validated policy on the server; idempotent creation or transactional WorkItem+Task creation; assistant never bypasses approval |
| Conversations | No conversation/message API | Ownership-scoped persistent conversations/messages; append idempotency; streaming event types separate from audit SSE; reconnect offsets, cancellation and delivery reconciliation; no model credentials in browser |
| Uploads | No upload/attachment API | Size/type limits, authorization, streamed storage, checksum, safe names, malicious-content handling; upload receipt bound to user/task; no arbitrary server file path or remote URL fetch |
| Artifact content | Artifact is a URI/sha256/size registry | Authorized content/preview delivery with expiry, MIME/download disposition and checksum verification; never relay arbitrary Artifact.uri as an unrestricted proxy |
| Production sessions | Local ephemeral issuer is intentionally loopback-only | Production identity adapter with server-side session validation, Secure/HttpOnly/SameSite cookies, CSRF/Origin checks, expiry/logout/revocation and role/object/worker scopes; unauthenticated private GET and SSE must fail closed |
| Durable workflow | Current local worker/ledger is simulation | Approved PG runtime wiring, transactions/CAS/idempotency, outbox lease/ACK semantics, failure and restart/restore evidence |

GLM should provide an additive, versioned OpenAPI diff and signed lock/examples after its review. Codex can then regenerate the SDK and connect the already separated workspace views. Do not add a shadow frontend API, pass arbitrary instructions through local.simulate, silently change the existing lock, label mock model calls LIVE or call old services to fill the gaps.

Production networking, identity setup, PG runtime and real model/Worker credentials require the user's separate gate authorization. This document contains no credentials and does not authorize those operations.
