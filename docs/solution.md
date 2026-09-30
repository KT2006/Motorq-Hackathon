# Fleet Intelligence Platform — Solution Document

## 1. Problem Statement
Commercial fleets incur avoidable operating costs through engine idling and poor vehicle utilisation. Raw GPS and telemetry data is too noisy to surface this waste directly. Fleet managers need to see the financial impact of their operations from raw coordinates, expressed in Indian rupees (INR).

## 2. Solution Overview
The Fleet Intelligence Platform ingests raw telemetry events at scale, runs a deterministic O(n) state machine to segment trips and idling, and calculates daily aggregated costs. A React dashboard and an embedded, tool-calling LLM agent surface these insights to fleet managers.

## 3. Architecture
*(See `docs/architecture.md` for C4 Context, Data Flow, Deployment Topology, and Sequence diagrams.)*
- **Ingestion:** Redpanda (Kafka compatible) + Python Consumer.
- **Storage:** PostgreSQL (with TimescaleDB extension) for telemetry, Redis for live status caching.
- **API:** FastAPI backend.
- **Frontend:** React + Vite SPA served via Nginx.

## 4. Key Design Decisions
*(See `docs/adrs.md` for full Architecture Decision Records)*
1. **PostgreSQL + TimescaleDB:** Ensures ACID guarantees for cost calculations while efficiently compressing time-series telemetry.
2. **Redpanda:** Low-ops, high-performance streaming for ingestion bursts.
3. **Tool-Calling Agent over RAG:** Structured database queries are strictly superior to semantic vector search for precise fleet metrics.
4. **Weighted Offender Scoring:** Combines idle cost, idle percentage, and absolute minutes to rank the genuinely worst offenders.

## 5. Data Model
The system uses PostgreSQL for relational data and TimescaleDB for time-series telemetry. The `telemetry_events` table uses TimescaleDB hypertable partitioning by time (`ts`), which transparently shards data to handle high-volume ingestion and fast time-based queries.

## 6. Segmentation Algorithm
*(See `docs/algorithms.md` for full details)*
Raw telemetry is processed into meaningful `trips` and `idle_events` using a deterministic O(n) state machine. It iterates over sorted events for each vehicle exactly once, maintaining running state to correctly identify periods of motion and idling.

## 7. Cost Calculation
Cost analysis uses a weighted scoring mechanism rather than a naive total. Fuel and idle costs are calculated using INR-denominated reference prices (₹/litre for liquid fuels and ₹/kWh for electricity); cost values are never currency-converted. The algorithm combines idle cost, idle percentage, and absolute idle minutes to rank the genuinely worst offenders, ensuring that vehicles with high utilization aren't unfairly penalized for naturally having more absolute idle time.

## 8. Security
- **Authentication:** JWT-based stateless auth. *Note on demo auth:* Demo credentials use a browser prompt to securely request the demo password.
- **Tenant Isolation:** Users receive tokens mapped to a specific `fleet_id`. The API strictly enforces this across ALL data endpoints (including cost summary, live status, and AI tool calls) by implicitly appending `fleet_id = %s` filter clauses.
- **Audit Logging:** Every AI request and sensitive API call is logged in the `audit_log` table with the user's identity, timestamp, and query details.

## 9. Performance
- **Connection Pooling:** PgBouncer is used for efficient database connection pooling.
- **Materialized Views:** Used for pre-aggregating monthly fleet totals, reducing scan times from milliseconds to sub-milliseconds.
- **Keyset Pagination:** The `/vehicles` API uses keyset pagination (`cursor` on `vin`) to provide O(1) page access at depth, rather than degrading offset limits.

## 10. Known Limitations
- **Demo Scale:** The default setup seeds 50 vehicles to run efficiently locally.
- **Target Scale:** 100K+ vehicles and 100K events/sec are architecturally supported (via sharding and partition strategies) but have not been formally benchmarked at that target scale.

## 11. Future Work
- Perform formal load testing at the 100K vehicle target scale.
- Add read replicas and Redis clustering for true horizontal scale.
