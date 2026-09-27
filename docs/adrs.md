# Architecture Decision Records (ADRs)

## ADR-01: Storage Choice & CAP Trade-off
**Decision:** Postgres (Supabase) for both relational core and telemetry, no separate NoSQL store.
**Reasoning:** Since our dataset fits comfortably in PostgreSQL (few million rows), a single system avoids the operational complexity of a polyglot architecture. While raw telemetry demands High Availability (AP), our financial reports (`cost_summary_daily`) demand Strong Consistency (CP). Supabase gives us CP, and we rely on the `telemetry_events` table acting as an append-only log to support high write volume.
**Consequences:** Simpler operations and a single source of truth, at the cost of not demonstrating a literal polyglot NoSQL store—mitigated by our optimized indexing strategy for the telemetry table.

## ADR-02: Rules-Based Scoring Over Trained Classifier
**Decision:** We implemented a weighted rules-based scoring engine for M5 rather than an ML classification model.
**Reasoning:** We do not have ground truth data labeling "good" vs. "bad" idling for this specific fleet context. A rules-based algorithm using relative percentages allows fleet managers to tune weights (cost vs time vs % of active time) transparently and avoid opaque "black box" flagging.
**Consequences:** Quick, interpretable baseline scoring that works immediately, though it may lack the nuance of a trained ML model over time.

## ADR-03: No Vector Store Used
**Decision:** We opted not to use a Vector Store/Embeddings database for the M9 AI Agent.
**Reasoning:** The agent interacts with numeric time-series data and structured relational queries (e.g. "which vehicles are idling the most?"). There is no semantic search or unstructured text retrieval requirement for this specific workflow.
**Consequences:** The agent executes SQL-backed tool calls directly, returning precise, deterministic financial numbers rather than retrieved semantic approximations.

## ADR-04: Ingestion Path — Direct Write vs. Streaming Consumer
**Decision:** Ingestion is currently a direct write from the simulator to Supabase rather than a Kafka/Redpanda streaming path.
**Reasoning:** Due to time constraints in a 72-hour hackathon, we scoped down the architecture to avoid managing a separate message broker. Data flows directly from the simulator to Supabase.
**Consequences:** We skipped a literal streaming consumer. However, we implemented the required streaming idempotency mechanisms in the database via a unique index and `ON CONFLICT DO NOTHING` to demonstrate how we would handle at-least-once delivery duplicates from a real stream.

## ADR-05: Idempotency Approach
**Decision:** Implemented `ON CONFLICT DO NOTHING` with a unique index on `(vin, ts, seq)` in `telemetry_events`.
**Reasoning:** Resolves duplicates from out-of-order or retried packet deliveries transparently in the database layer. By ordering `ORDER BY ts ASC, seq ASC` in downstream queries, out-of-order inserts are handled safely.
**Consequences:** Guarantees idempotency without requiring complex state tracking in an intermediate ingestion service.
