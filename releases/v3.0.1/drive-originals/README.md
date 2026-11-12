# Historical evidence — not a deployment procedure

These six files preserve the original Drive bytes, including the 4,812-byte
START-HERE and both JSON metadata files. MANIFEST.json records their sizes,
SHA-256 values and Drive IDs. The original SHA256.json verifies five entries;
its own digest is recorded separately. `patches/v3.0.1.patch` is an unchanged
second copy of PATCH.diff.

Statements about deployment, memory, public authentication, authorship or a
local tag inside these files are the original author's reports. They are not
independent production acceptance evidence. The source tree was reconstructed
from the patch; the original `2fa330f7` Git commit object/history was not recovered.

Do not execute the old public proxy instructions: they rewrite Origin to a
loopback value and expose an unauthenticated local session issuer. The tag in
the original clone command was absent on the remote when checked. One-shot
service state and HTTP 200 do not establish application health.

Use [the US portal handoff](../../../docs/US-PORTAL-INTEGRATION.md) and
[the current GLM handoff](../../../docs/GLM-DEPLOYMENT-HANDOFF.md). No tag is
created by this restoration; it does not deploy anything.
