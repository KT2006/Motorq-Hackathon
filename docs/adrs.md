# Architecture Decision Records (ADRs)

## ADR-1: PostgreSQL + TimescaleDB for primary storage

**Status:** Accepted  
**Date:** 2026-09-29  
**Context:** Need to store telemetry events (100K+/sec target), trips, idle events, cost summaries. Need time-series queries, standard SQL joins for cost rollup, and ACID guarantees.  
**Decision:** PostgreSQL with TimescaleDB hypertable for telemetry_events. Standard relational tables for master data and aggregates.  
**Alternatives Considered:** InfluxDB (no SQL joins), Apache Druid (complex ops), ClickHouse (no ACID), DynamoDB (expensive at scale).  
**Consequences:** Flexible SQL joins and familiar operations. The local demo uses a single node; its write ceiling has not been established. The measured short streaming test is documented in `scale-benchmark.md` and is well below the challenge target. Production capacity, compression, partitioning, and replicas require workload-specific validation; no compression policy is enabled in the local Compose setup.

## ADR-2: Redpanda for event streaming over Apache Kafka

**Status:** Accepted  
**Date:** 2026-09-29  
**Context:** Need a message broker for a replayable telemetry streaming path and consumer groups. The local configuration is a single broker and has not been qualified for the challenge burst target.
**Decision:** Redpanda (Kafka-compatible, single-binary, no JVM/ZooKeeper).  
**Alternatives Considered:** Apache Kafka (heavier ops), RabbitMQ (no log replay), AWS Kinesis (vendor lock-in).  
**Consequences:** Lower ops overhead, same Kafka protocol. Community edition sufficient for hackathon. Production would evaluate Redpanda Cloud or managed Kafka.

## ADR-3: O(n) state-machine segmentation over database-side window functions

**Status:** Accepted  
**Date:** 2026-09-29  
**Context:** Need to segment raw telemetry into trips and idle events. Two approaches: SQL window functions or application-level state machine.  
**Decision:** Application-level O(n) state machine in Python (segment.py). States: NOT_IN_TRIP → DRIVING → IN_TRIP_IDLE.  
**Alternatives Considered:** SQL window functions (LAG/LEAD), dbt models, Flink stateful processing.  
**Consequences:** Deterministic, unit-testable, handles edge cases (unclosed trips, midnight boundaries). Easier to debug than complex SQL. Trade-off: runs in Python (slower than native SQL for very large datasets), but segmentation is embarrassingly parallel per VIN.

## ADR-4: Weighted multi-factor scoring over naive threshold for offender ranking

**Status:** Accepted  
**Date:** 2026-09-29  
**Context:** Need to rank vehicles by "worst idling offenders." Simple approach: threshold on total idle minutes. Problem: high-utilization vehicles with moderate absolute idle get missed; low-utilization vehicles with high idle percentage get missed.  
**Decision:** Weighted composite score: W_COST × normalized_idle_cost + W_PCT × idle_pct_of_active + W_MIN × normalized_idle_minutes. All weights = 1.0 (equal). Normalization against fleet-wide max values.  
**Alternatives Considered:** Single-metric ranking (idle minutes only), ML clustering, percentile-based.  
**Consequences:** The weighted score captures cost, relative idle share, and idle volume; a unit test demonstrates one case where its result differs from the naive threshold. This does not prove better real-world predictions. Weights are tunable per fleet operator. Trade-off: score is relative to the fleet, not absolute.

## ADR-5: Database-backed assistant answers over RAG/vector-store

**Status:** Accepted  
**Date:** 2026-09-29  
**Context:** Fleet metrics must remain accurate and consistent across assistant responses.
**Decision:** Query fleet metrics with parameterized PostgreSQL aggregates, pass the compact results and date/fleet scope as authoritative context to the Groq-hosted LLM, then return its answer to the user. Do not expose direct SQL generation or allow the model to fetch fleet data itself.
**Alternatives Considered:** Vector-store RAG (overkill for structured data), text-to-SQL (injection risk), deterministic templates that do not let the model formulate the response.
**Consequences:** Each turn receives fresh database context for the same pinned reporting period; recommendations can be conversational while measured figures originate from SQL. The external model can still misstate context, so its prompt explicitly forbids invented values and savings; the service remains dependent on Groq availability.

## Storage Role Justification

| Store | Role | Why This Store | Failure Behavior |
|-------|------|----------------|------------------|
| PostgreSQL (TimescaleDB) | Telemetry, trips, idles, costs, audit | SQL joins for cost rollup and transactional event writes | Consumer retries uncommitted batches; event-key conflict handling makes repeated DB inserts idempotent |
| Redis | Live vehicle status cache | Ephemeral latest status with TTL | API reports missing/unavailable status when no cache entry exists; cross-store consistency is not atomic |
| Redpanda | Event streaming | Kafka-compatible topic and consumer-group offset tracking | Replay is possible from uncommitted offsets; local burst capacity is unverified and dead-letter send failures may still be followed by offset commits |
| No vector store | Fleet metrics are queried directly with SQL | Structured fleet data is better served by SQL than semantic search | N/A |
