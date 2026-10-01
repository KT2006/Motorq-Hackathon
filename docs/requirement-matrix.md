# Requirement Traceability and Evidence

Status describes evidence actually available in this repository or the local
run. “Implemented” does not imply the scale, security, or reliability target
has been independently validated.

| # | Requirement | Implementation | Evidence | Status |
|---|---|---|---|---|
| R1 | Segment telemetry into trips and idles | `services/segmentation/segment.py` O(n) state machine | `tests/test_segmentation.py`, `tests/test_seed_profile.py` | **Implemented; unit tested** |
| R2 | Daily vehicle fuel/idle cost rollups | `services/segmentation/cost_engine.py` | `tests/test_cost_calc.py`, `tests/test_cost_engine_logic.py`; fresh run produced 7,000 daily rows | **Implemented; local demo verified** |
| R3 | Rank idle-cost offenders | Weighted score and `/fleet/offenders` | Cost calculation tests; API returned 1,000 total offenders in fresh demo | **Implemented; local demo verified** |
| R4 | Live status cache | Ingestion consumer updates Redis; API reads live status | Redis and endpoint exist; live cache behavior is not fully covered by the fresh-seed count check | **Partial** |
| R5 | Streaming ingestion | Redpanda consumer and batch Postgres writes | 10,000-event local functional check; ~8,234 events/s end-to-end | **Implemented; throughput target unmet** |
| R6 | Validate telemetry schemas | Pydantic event model | `tests/test_api_contracts.py` | **Implemented; contract tests exist** |
| R7 | Idempotent ingestion | Unique event key and `ON CONFLICT DO NOTHING` | `tests/test_ingestion_idempotency.py`; duplicate events in simulator | **Implemented; tests exist** |
| R8 | Useful web dashboard | Overview, paginated leaderboard, vehicle detail, assistant | Fresh local dashboard/API smoke check; UI walkthrough still needed in submission video | **Local demo verified** |
| R9 | Fleet-data-aware assistant | SQL context is passed to optional Groq LLM | `tests/test_ai_assistant.py`; depends on external key/service | **Implemented; optional path** |
| R10 | JWT authentication | `/token` and protected routes | Fresh Compose login and protected API request succeeded | **Local demo verified; demo credentials only** |
| R11 | API rate limiting | SlowAPI route limits | Configured in API; no current soak/burst validation | **Implemented; load behavior partial** |
| R12 | One-command local start | Docker Compose services; API waits for seeder | Fresh `docker compose up --build` completed after fixing a Decimal-capacity failure | **Local workflow verified** |
| R13 | At least 100K simulated vehicles | `SEED_MODE=full` code path | Full profile is 100K × 1 day but has not been run; verified default is 1K × 7 days | **Not verified; acceptance target unmet** |
| R14 | 100K events/s and 3× five-minute burst without loss | Redpanda + consumer; performance harness | Short local stream result ~8.2K events/s; no sustained 100K or burst test | **Not met / not verified** |
| R15 | At least 80% core-service coverage | Pytest/coverage workflow | Saved focused run reports 35% total across measured modules; not a full current-suite report | **Not met** |
| R16 | Security scan | Trivy report in `docs/trivy_scan_api.txt` | Saved scan is for an earlier image: 44 HIGH, 53 MEDIUM, 0 CRITICAL | **Partial; rescan current images** |
| R17 | 3–5 architecture decisions | `docs/adrs.md` | Five ADRs documented | **Documented** |
| R18 | Current OpenAPI contract | `docs/openapi.json` | File exists; synchronization with latest API changes has not been confirmed | **Partial; regenerate/compare** |
| R19 | Tenant isolation | JWT fleet claim and query filters | `tests/test_security.py` | **Implemented; expand endpoint-level authorization tests** |
| R20 | Audit trail for data access and AI actions | `audit_log` and `agent_logs` | Selected reads and chat calls log; failures are swallowed/logged and coverage is not comprehensive | **Partial; not every access guaranteed** |
| D1 | Completed solution document and ≤5-minute demo video | `docs/solution.md` and recording | Solution write-up is a project summary; team/submission metadata and video link are not provided | **Pending completion** |
| D2 | Cloud deployment, cloud agnosticism, HA | Kubernetes and Terraform scaffolding | Artifacts are explicitly untested; local Compose is single-node | **Planned / unverified** |
| D3 | Observability, privacy, compliance, erasure | Logs and lifecycle notes | No verified centralized metrics/traces, location masking, or right-to-erasure flow | **Not demonstrated** |

The challenge's minimum bar includes a working **100,000-vehicle** dataset;
neither a 1,000- nor a 50,000-vehicle run should be represented as satisfying
that requirement. A dataset-size pass also does not establish the separate
100,000-events/sec throughput or burst requirement.
