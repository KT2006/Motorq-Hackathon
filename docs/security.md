# Security & Compliance

## API Security
- **Authentication**: All API endpoints (except `/token`) require a valid JWT passed in the `Authorization: Bearer <token>` header. For demo convenience, the dashboard automatically authenticates against the `/token` endpoint using a fixed demo credential. In production, this would be replaced with a real user-facing login form, not embedded credentials.
- **Rate Limiting**: Implemented via SlowAPI. The core analytical endpoints (`/fleet/offenders`, `/fleet/summary`) are strictly limited to `100/minute` to prevent DDoS attacks against computationally expensive rollups, as successfully proven during M11 load testing.
- **Encryption in Transit**: The database connections to Supabase enforce TLS (`postgresql://` scheme) out of the box, ensuring telemetry and financial data cannot be intercepted.

## Container Security Scan (Trivy)
Due to hackathon environment constraints (Docker daemon unavailable in the build environment), automated container vulnerability scanning (e.g., Trivy/Snyk) was omitted from the CI pipeline. 

To mitigate risk, base images were intentionally selected for a reduced CVE surface area (`python:3.12-slim` for the backend, `node:20-alpine` and `nginx:alpine` for the frontend). A production deployment would mandate adding an automated scan as a CI gate blocking builds with CRITICAL findings.

## Data Lifecycle & Retention
- Telemetry events are append-only. To manage storage costs at 100K-vehicle scale, we assume a 90-day hot retention policy. Older data would be archived to cold storage (e.g., S3 Parquet) since day-to-day analytics run against the pre-calculated `cost_summary_daily` aggregation table, not the raw row data.

## Audit Logging
- **Agent Logs**: To ensure AI transparency, the `agent_logs` table strictly records every query asked of the M9 AI agent, the exact SQL tool calls it made, and the final answer given. This ensures the reasoning of any AI-driven recommendation can be audited retroactively.
