# Security & Compliance

## API Security

- **Authentication**: All API endpoints (except `/token`) require a valid JWT passed in the `Authorization: Bearer <token>` header. For this hackathon demo, Compose passes `DEMO_PASSWORD` to the dashboard build as `VITE_DEMO_PASSWORD`, which is embedded in the public JavaScript bundle; do not use this credential flow with sensitive data or in production.
- **Rate Limiting**: Implemented via SlowAPI. Core analytical endpoints are limited to `100/minute`; the `/chat` AI endpoint is limited to `20/minute` to prevent abuse of the LLM API.
- **Encryption in Transit**: Supabase connections enforce TLS by default. Local Docker networking uses plaintext (acceptable for local dev only; a production deploy behind a load balancer or reverse proxy would terminate TLS there).
- **CORS**: Currently set to `allow_origins=["*"]` — appropriate for a hackathon demo; a production deployment would scope this to the specific dashboard origin.

## STRIDE Threat Model — Ingestion Path & Public API

| # | STRIDE Category | Threat | Affected Component | Control |
|---|---|---|---|---|
| 1 | **Spoofing** | Attacker sends telemetry events with a spoofed VIN, injecting false data into `telemetry_events` | Redpanda ingestion topic | Authenticate producers at the broker level (SASL/SCRAM in production); VIN format validation in the consumer's Pydantic schema rejects malformed payloads |
| 2 | **Tampering** | Man-in-the-middle modifies in-flight telemetry events between the vehicle and Redpanda | Network layer (producer → broker) | Enforce mTLS between producers and Redpanda; idempotency key `(vin, ts, seq)` means re-injected events are harmless no-ops |
| 3 | **Repudiation** | Fleet manager denies asking the AI agent a question that triggered a cost recommendation | AI agent (`/chat` endpoint) | Every agent request, tool call, and final answer is persisted in `agent_logs` with timestamp — provides a full audit trail |
| 4 | **Information Disclosure** | Unauthenticated caller reads fleet cost data or vehicle positions | FastAPI public API | All endpoints (except `/token`) require a valid JWT; JWT uses HS256 with a secret stored only in env vars (never in source); rate limiting prevents enumeration |
| 5 | **Denial of Service** | Attacker floods `/fleet/offenders` (an expensive aggregation query) to exhaust DB connections | FastAPI → PostgreSQL | SlowAPI rate limiter (100 req/min per IP) returns 429 before the query runs; `cost_summary_daily` pre-aggregation means the query is O(1) not O(N) against raw telemetry |

*Elevation of Privilege (E) is not the primary concern in a read-heavy analytics API with no write surface exposed to users; the agent's tools are read-only by design (documented in ADR-03).*

## Container Security (Trivy)

A Trivy scan of the API image is committed to `docs/trivy_scan_api.txt`.

**Honest disclosure:** The scan reports 44 high-severity findings, all in base OS packages (`python:3.12-slim`). No critical findings. These are acknowledged as technical debt. A production release would:
1. Pin to a hardened base image (e.g., `cgr.dev/chainguard/python:latest`)
2. Run Trivy as a CI gate blocking merges with CRITICAL findings
3. Subscribe to base image update notifications

## Data Lifecycle & Retention

- Telemetry events are append-only with an `ON CONFLICT DO NOTHING` idempotency guarantee on `(vin, ts, seq)`.
- Assumed hot retention policy: 90 days of raw `telemetry_events`. Older data would be archived to cold storage (e.g., S3 Parquet) — day-to-day analytics run against `cost_summary_daily`, not raw rows.
- GPS coordinates are retained at full precision for 90 days, then aggregated to trip-level origin/destination only — balancing operational utility against privacy.

## Audit Logging

Every query asked of the M9 AI agent is recorded in `agent_logs` with the exact tool calls made and the final answer. This ensures every AI-driven recommendation is retroactively auditable and satisfies the compliance requirement for "audit logs for every AI-agent action."

## VITE_* Variable Disclosure

The `VITE_DEMO_PASSWORD` environment variable is injected at build time and embedded in the compiled JavaScript bundle. This is publicly discoverable by anyone with access to the frontend bundle. This is acceptable for a hackathon demo (the only data at risk is synthetic fleet data). In production, this would be replaced with a proper server-side session flow where credentials are never embedded in the frontend bundle.
