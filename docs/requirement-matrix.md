# Requirement Traceability Matrix

| # | Requirement | Implementation Path | Test/Evidence | Status |
|---|-------------|-------------------|---------------|--------|
| R1 | Process raw telemetry into trips and idle events | `services/segmentation/segment.py` — O(n) state-machine | `tests/test_segmentation.py` (5 tests) | ✅ Done |
| R2 | Calculate fuel and idle costs per vehicle per day | `services/segmentation/cost_engine.py` — ROLLUP_SQL | `tests/test_cost_calc.py` (4 tests) | ✅ Done |
| R3 | Top-K worst offenders ranking (weighted vs naive) | `cost_engine.py` TOP_K_WEIGHTED_SQL + `/fleet/offenders` | `test_cost_calc.py::test_baseline_vs_weighted_score_disagree` | ✅ Done |
| R4 | Live vehicle status (Redis cache) | `services/ingestion/consumer.py` → Redis hash | `/vehicles/{vin}/live-status` endpoint | ✅ Done |
| R5 | Streaming ingestion (Redpanda) | `services/ingestion/consumer.py` + `producer.py` | Consumer lag logging, DLQ for malformed events | ✅ Done |
| R6 | Schema validation on ingest | `consumer.py` — Pydantic `TelemetryEvent` model | `tests/test_api_contracts.py` (8+ tests) | ✅ Done |
| R7 | Idempotent ingestion (dedup) | `ON CONFLICT (vin, ts, seq) DO NOTHING` | `tests/test_ingestion_idempotency.py`, seeder injects duplicates | ✅ Done |
| R8 | React dashboard with overview, leaderboard, drill-down | `dashboard/src/components/` — 4 views | Visual inspection + smoke test | ✅ Done |
| R9 | Assistant answers grounded in fleet data | `services/api/main.py` — `/chat` supplies SQL metrics as LLM context | `tests/test_ai_assistant.py`; audit log in `agent_logs` | ✅ Done |
| R10 | JWT authentication | `main.py` — `verify_token()` + `/token` | Auth required on all data endpoints | ✅ Done |
| R11 | Rate limiting | `slowapi` on all endpoints (100/min, 20/min for chat) | Rate limit headers in API responses | ✅ Done |
| R12 | Docker Compose one-command startup | `docker-compose.yml` — 6 services | `docker compose up --build` | ✅ Done |
| R13 | 100K+ vehicle synthetic data | `simulator/data_simulator.py` — multiprocessing-ready | Documented scaling path | ⚠️ Architecture supports, demo seeds 50 |
| R14 | 100K events/sec throughput target | Architecture supports it, benchmark needed | `locustfile.py` for load testing | ⚠️ Not benchmarked at target scale |
| R15 | 80%+ test coverage | `pytest --cov` on segmentation modules | `docs/coverage-report.txt` | ⚠️ Current: ~42% |
| R16 | Security scan | Trivy container scan | `docs/trivy_scan_api.txt` | ✅ Done |
| R17 | ADRs (3-5) | `docs/adrs.md` | 5 ADRs documented | ✅ Done |
| R18 | OpenAPI spec | `docs/openapi.json` | Sync with running API | ✅ Done |
| R19 | Fleet/tenant isolation | JWT `fleet_id` claim + API query filtering | Negative tests in test_security.py | ✅ Done |
| R20 | Audit logging | `audit_log` table + middleware | Data access and AI queries logged | ✅ Done |
