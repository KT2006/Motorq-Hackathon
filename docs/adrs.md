# Architecture Decision Records (ADRs)

## ADR-1: PostgreSQL + TimescaleDB for primary storage

**Status:** Accepted  
**Date:** 2026-09-29  
**Context:** Need to store telemetry events (100K+/sec target), trips, idle events, cost summaries. Need time-series queries, standard SQL joins for cost rollup, and ACID guarantees.  
**Decision:** PostgreSQL with TimescaleDB hypertable for telemetry_events. Standard relational tables for master data and aggregates.  
**Alternatives Considered:** InfluxDB (no SQL joins), Apache Druid (complex ops), ClickHouse (no ACID), DynamoDB (expensive at scale).  
**Consequences:** Excellent query flexibility, familiar SQL. TimescaleDB compression for storage. Single-node may limit write throughput past ~50K events/sec; horizontal partitioning or read replicas needed at true production scale.

## ADR-2: Redpanda for event streaming over Apache Kafka

**Status:** Accepted  
**Date:** 2026-09-29  
**Context:** Need a message broker for the telemetry streaming pipeline. Must handle bursty traffic, replay, and consumer groups.  
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
**Consequences:** Provably better signal than naive threshold (test_cost_calc.py demonstrates a case where rankings differ). Weights are tunable per fleet operator. Trade-off: score is relative to the fleet, not absolute.

## ADR-5: Tool-calling LLM agent over RAG/vector-store

**Status:** Accepted  
**Date:** 2026-09-29  
**Context:** AI assistant needs to answer fleet questions using real data. Options: vector-store RAG over documents, direct SQL generation, or tool-calling with structured API endpoints.  
**Decision:** Groq-hosted LLM (llama/mixtral) with tool-calling. Two tools: get_fleet_offenders and get_vehicle_cost_summary. Bounded loop (max 5 iterations, 30s timeout).  
**Alternatives Considered:** Vector-store RAG (overkill for structured data), text-to-SQL (injection risk), pre-computed answers.  
**Consequences:** Grounded in real data (tool results, not hallucinations). Read-only tools prevent data mutation. Audit trail via agent_logs table. Trade-off: depends on external LLM API availability; graceful fallback added.
