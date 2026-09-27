# Security, NFR & Observability (M10)

## 1. TLS Confirmation

Database connections to Supabase use TLS by default (enforced at the platform level). Our FastAPI service itself runs over HTTP locally for development; for the deployed/documented cloud version, TLS termination would sit at the load balancer/ingress layer (standard pattern, documented in our Terraform/K8s manifests even if not live-deployed).

## 2. Location-Data Masking & Retention Policy

Raw GPS telemetry (`telemetry_events`) is retained for 90 days to support trip/idle segmentation and debugging. After 90 days, raw location pings are eligible for deletion, retaining only the aggregated `trips` and `cost_summary_daily` records, which contain trip-level start/end coordinates but not the full continuous location trace. This limits how long precise, continuous location history exists for any given vehicle/driver, while preserving the cost/utilisation insights the product depends on long-term. A scheduled job (not implemented in this hackathon scope, but described here) would enforce this retention window in production.

## 3. STRIDE Threat Model

This threat model is scoped to our ingestion path and public API.

| Threat (STRIDE category) | Scenario | Control |
|---|---|---|
| **Spoofing** | Someone impersonates a legitimate vehicle/OEM and pushes fake telemetry | JWT auth required on write paths; device-level auth per source in production. |
| **Tampering** | An attacker modifies telemetry data in transit or intercepts API responses | TLS on all DB connections (Supabase default); JWT signature prevents token tampering. |
| **Repudiation** | A fleet manager or the AI agent takes an action and later denies it | Audit log table (`agent_logs` from M9) records every agent query + tool call + response with timestamps. |
| **Information Disclosure** | Vehicle location/cost data leaks to an unauthorized party | JWT-protected endpoints (no anonymous access to `/vehicles`, `/fleet/offenders`, etc.). |
| **Denial of Service** | Someone floods the API with requests, degrading service for real users | Rate limiting middleware (per-token/per-IP limits of 100/min, from M7). |
