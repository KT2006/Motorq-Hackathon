# Security & Compliance

## API Security & OWASP Considerations

Our API security model is built around OWASP API Top 10 recommendations:

- **Authentication & Secret Management**: All API endpoints (except `/token`) require a valid JWT passed in the `Authorization: Bearer <token>` header. JWT authentication uses environment-configured secrets with NO hardcoded defaults. Secrets are managed strictly via environment variables, and the `.env.example` file contains placeholders only.
- **Tenant Isolation**: Fleet/tenant isolation is enforced via a JWT `fleet_id` claim, preventing cross-tenant data access (BOLA/IDOR protection).
- **Rate Limiting**: Implemented via SlowAPI to prevent DoS and abuse. Core analytical endpoints are limited to `100/minute`; the `/chat` AI endpoint is limited to `20/minute`.
- **Encryption in Transit**: Supabase connections enforce TLS by default. Local Docker networking uses plaintext. TLS is highly recommended for all production deployments.
- **CORS**: Currently set to `allow_origins=["*"]` for the hackathon demo. In production, CORS must be restricted to known origins (e.g., the specific dashboard domain).
- **Input Validation**: Strict input validation is enforced via Pydantic models on all API requests and message queue consumers. Malformed events are routed to a dead-letter queue (DLQ) for inspection rather than crashing the consumer or polluting the database.
- **Audit Logging**: Comprehensive audit logging is maintained for sensitive data access and AI queries. Every query to the M9 AI agent is recorded in `agent_logs` with exact tool calls and answers, ensuring traceability and accountability.

## STRIDE Threat Model — Ingestion Path & Public API

| # | STRIDE Category | Threat | Affected Component | Control |
|---|---|---|---|---|
| 1 | **Spoofing** | Attacker sends telemetry events with a spoofed VIN, injecting false data into `telemetry_events` | Redpanda ingestion topic | Authenticate producers at the broker level; VIN format validation in the consumer's Pydantic schema rejects malformed payloads to DLQ. |
| 2 | **Tampering** | Man-in-the-middle modifies in-flight telemetry events | Network layer (producer → broker) | Enforce mTLS between producers and Redpanda; idempotency key `(vin, ts, seq)` prevents replay attacks. |
| 3 | **Repudiation** | Fleet manager denies asking the AI agent a question that triggered a cost recommendation | AI agent (`/chat` endpoint) | Every agent request, tool call, and final answer is persisted in `agent_logs` with timestamp — provides a full audit trail. |
| 4 | **Information Disclosure** | Unauthenticated caller reads fleet cost data or vehicle positions | FastAPI public API | All endpoints require a valid JWT with `fleet_id` claim; JWT uses HS256 with a secret stored only in env vars. |
| 5 | **Denial of Service** | Attacker floods expensive aggregation queries to exhaust DB connections | FastAPI → PostgreSQL | Rate limiter (100 req/min per IP) returns 429 before the query runs. |

*Elevation of Privilege (E) is not the primary concern in a read-heavy analytics API with no write surface exposed to users; the agent's tools are read-only by design.*

## Container Security (Trivy)

A Trivy scan of the API image is committed to `docs/trivy_scan_api.txt`.
The scan reports findings in base OS packages (`python:3.12-slim`). No critical findings. These are acknowledged as technical debt. A production release would:
1. Pin to a hardened base image (e.g., `cgr.dev/chainguard/python:latest`)
2. Run Trivy as a CI gate blocking merges with CRITICAL findings
3. Subscribe to base image update notifications

## Data Lifecycle & Retention

- Telemetry events are append-only with an `ON CONFLICT DO NOTHING` idempotency guarantee.
- Assumed hot retention policy: 90 days of raw `telemetry_events`. Older data would be archived to cold storage.
- GPS coordinates are retained at full precision for 90 days, then aggregated to trip-level origin/destination only.
