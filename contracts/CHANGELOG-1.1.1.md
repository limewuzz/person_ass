# Local integration compatibility revision 1.1.1

Baseline SHA: 18b42a97b3f975fcbe9a0326a1374d56fa547268e6fdefd18dc9cb529e8f7a25.
Current SHA: e4194aa3d00dd1dca300010d7dc85e94b3d9da0a07a25c3fc977b092677cd1fa.

The user authorized fixes in an independent backend copy. Original GLM package and production remain unchanged.

Preserved: all 41 paths / 43 operations, operationIds, request shapes, original required response fields and enum values.
Compatible additions: optional redacted Task/Approval context; explicit dependency 503 responses; ReadinessStatus 503 carries honest not_ready/database not_connected instead of pretending successful readiness. Baseline YAML and lock are retained byte-for-byte under contracts/baseline.

Runtime corrections implement the promised contract: UUID ledger IDs; uppercase approval/integration states; DataSourceMeta fields; bootstrap LOCAL_MOCK and identity; NodeList dashboard envelope; 201 WorkItem and 202 TaskAccepted/cancel Task; complete request idempotency; no browser Worker access; versioned authority/approval/lease guards.

Data source is LOCAL_MOCK. PG runtime, production identity, external probes and deployment remain unapproved/unrun. A matching contract SHA is not a production-readiness claim.
