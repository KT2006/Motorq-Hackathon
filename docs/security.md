# Security and Data Lifecycle

This is a local hackathon demo, not a production security posture. The controls
below describe implemented behavior and known gaps; they are not a compliance
certification.

## Implemented controls

| Area | Current behavior | Limitation |
|---|---|---|
| Authentication | Protected API routes require a JWT; `/token` issues demo tokens. | Compose supplies a known local fallback user/password and signing key so judges need no secrets file. Never expose these defaults publicly. |
| Tenant scope | JWT contains a fleet claim; API queries apply the fleet filter for non-admin users. | Expand endpoint-level negative authorization tests before deployment. |
| Request limits | SlowAPI rate limits are configured on API routes. | No sustained overload or distributed-rate-limit validation. |
| Input validation | Pydantic validates incoming telemetry; malformed JSON/schema records are sent to a dead-letter topic on a best-effort basis. | DLQ send failures are logged, but the current consumer may still commit offsets; broker authentication and schema-registry governance are not configured. |
| CORS | API uses an explicit `CORS_ORIGINS` allowlist; Compose supplies local development origins. | Recheck values in any deployed environment. |
| Audit records | Selected sensitive reads and chat requests write to `audit_log`; AI exchanges also use `agent_logs`. | Auditing is not comprehensive. Audit-write failures are logged and do not fail the request. |

## STRIDE snapshot

| Threat | Current mitigation | Remaining work |
|---|---|---|
| Spoofed telemetry producer | Event schema validation and VIN format checks | Authenticate producers at the broker; a valid-looking VIN is not proof of ownership. |
| Event tampering in transit | Event identity key `(vin, ts, seq)` makes database writes idempotent | Configure TLS/mTLS; idempotency does not prevent a malicious actor from fabricating valid events. |
| Repudiation of AI requests | Selected requests and answers are stored in application logs | Make audit writes durable, complete, and failure-aware; verify retention/access controls. |
| Unauthorized data access | JWT auth and fleet filters | Add broad cross-tenant negative tests and production identity/RBAC controls. |
| API/resource exhaustion | Per-route rate limits; PgBouncer is present in Compose but the API currently connects directly to Postgres | Test 3× burst, connection exhaustion, and recovery behavior; route API connections through the pooler if that is an intended control. |

## Image scan

`docs/trivy_scan_api.txt` is a saved scan of an earlier API image. It reported
44 HIGH, 53 MEDIUM, and 0 CRITICAL OS-package findings. It is not a scan of the
latest rebuilt image. Rescan current pinned images and address or formally
accept findings before any deployment.

## Transport, storage, and retention

- The local dashboard/API and container network use plaintext HTTP.
- Postgres, Redis, and Redpanda use temporary filesystems in local Compose;
  `docker compose down -v` removes the stack and associated anonymous volumes.
- The demo does not implement a verified hot/warm/cold retention policy,
  location masking, or GDPR/DPDP right-to-erasure workflow.
- The local demo uses synthetic data only. Do not load real personal or vehicle
  owner data.

## Production readiness

Before internet exposure, replace all demo credentials and signing keys with
managed secrets, terminate TLS, enable broker authentication, configure
least-privilege identities and complete tenant authorization tests, make
auditing durable, and verify retention/erasure and recovery procedures.
