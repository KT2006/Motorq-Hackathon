# Architecture Decision Records (ADRs)

## ADR-01: Storage Choice & CAP/PACELC Trade-offs
**CAP decision:**
- `cost_summary_daily`, `vehicles`, `fleets`, `trips` → CP (Consistency over Availability). These hold financial/billing-adjacent numbers where a stale or inconsistent read is worse than a slower or occasionally-unavailable one.
- `telemetry_events` (raw) → AP (Availability over Consistency). Raw telemetry is high-volume and append-only; losing strict consistency guarantees here in favor of always accepting writes is an acceptable trade, since correctness is enforced downstream during segmentation, not at raw ingest.

**PACELC extension:**
Under PACELC, our system is **PC/EC** — even in normal operation (no partition), we choose Consistency over Latency for the financial rollup path. Concretely: `cost_summary_daily` is only written by a batch job (M5) that recomputes it from `trips`/`idle_events`, rather than being updated incrementally on every event. This means the numbers a fleet manager sees are always internally consistent, at the cost of not reflecting the very latest telemetry until the next rollup run.
We mitigate the latency cost this would otherwise impose on the dashboard by separating write-latency from read-latency: the *write* path (the batch rollup) can be slow because it's a background job; the *read* path (dashboard/API queries against the pre-computed `cost_summary_daily` table) stays fast (sub-second) because it's reading an already-aggregated table instead of computing the aggregate live on every request.

## ADR-02: Rules-Based Scoring Over Trained Classifier
**Decision:** We implemented a weighted rules-based scoring engine for M5 rather than an ML classification model.
**Reasoning:** We do not have ground truth data labeling "good" vs. "bad" idling for this specific fleet context. A rules-based algorithm using relative percentages allows fleet managers to tune weights (cost vs time vs % of active time) transparently and avoid opaque "black box" flagging.
**Consequences:** Quick, interpretable baseline scoring that works immediately, though it may lack the nuance of a trained ML model over time.

## ADR-03: No Vector Store Used
**Decision:** We opted not to use a Vector Store/Embeddings database for the M9 AI Agent.
**Reasoning:** The agent interacts with numeric time-series data and structured relational queries (e.g. "which vehicles are idling the most?"). There is no semantic search or unstructured text retrieval requirement for this specific workflow.
**Consequences:** The agent executes SQL-backed tool calls directly, returning precise, deterministic financial numbers rather than retrieved semantic approximations.

## ADR-04: Ingestion Path — Streaming Consumer
**Decision:** Real-time ingestion is demonstrated via a Redpanda producer/consumer pair (`/services/ingestion/`), using the existing idempotent `ON CONFLICT DO NOTHING` constraint on `(vin, ts, seq)`.
**Reasoning:** Bulk historical data continues to load via direct batch insert for volume/performance reasons; the streaming path proves the ingestion mechanism end-to-end, including duplicate-event handling.
**Consequences:** Proves a robust streaming architecture capable of handling real-time telemetry while demonstrating handling of at-least-once delivery duplicates.

## ADR-06: Polyglot Persistence — Live Vehicle Status Cache
**Decision:** Live vehicle status is cached in Redis rather than served from Postgres.
**Reasoning:** This data is high-write-frequency, ephemeral, and doesn't need durability or ACID guarantees — losing a few seconds of cached status on restart is acceptable, whereas losing a `cost_summary_daily` row is not. This is a deliberate PACELC split within our own architecture: `cost_summary_daily` is PC/EC (Consistency prioritized, per ADR-01), while `vehicle:*:status` in Redis is PA/EL (Availability and low latency prioritized) — sub-millisecond reads for a live-status lookup, at the cost of not being the durable source of truth.
**Consequences:** Demonstrates a targeted use of NoSQL where it fits best alongside our relational core data.

## ADR-05: Idempotency Approach
**Decision:** Implemented `ON CONFLICT DO NOTHING` with a unique index on `(vin, ts, seq)` in `telemetry_events`.
**Reasoning:** Resolves duplicates from out-of-order or retried packet deliveries transparently in the database layer. By ordering `ORDER BY ts ASC, seq ASC` in downstream queries, out-of-order inserts are handled safely.
**Consequences:** Guarantees idempotency without requiring complex state tracking in an intermediate ingestion service.
