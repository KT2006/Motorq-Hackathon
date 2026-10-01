# Query optimisation evidence

This document records historical query-plan observations from a small
development dataset. They illustrate useful PostgreSQL techniques; they do
**not** establish query latency or capacity at 100K vehicles or production
scale. The figures below should be reproduced against the current schema and
workload before being used as current benchmark claims.

## Dataset and scope

The recorded plan run used 2,280 `cost_summary_daily` rows derived from
100,000 telemetry events across 85 vehicles. It profiled a fleet daily
aggregation, a top-K offender query, and a vehicle trend query using
`EXPLAIN (ANALYZE, BUFFERS)`. These values describe that run only.

## Fleet-wide daily aggregation

The original plan reported a sequential scan over 2,280 rows and 12.837 ms
total execution time. The tested covering index was:

```sql
CREATE INDEX idx_cost_summary_date_costs
ON cost_summary_daily (summary_date)
INCLUDE (fuel_cost, idle_cost, utilisation_pct);
```

The recorded plan then used an index-only scan with zero heap fetches and
13 buffer reads; its reported scan-node time was 2.557–13.956 ms. These plan
snippets are historical measurements, not a controlled before/after latency
comparison: the recorded after scan-node interval is not itself evidence of a
faster query, and buffer cache state affects results. Index selection also
depends on table size, selectivity, visibility-map coverage, and statistics.

Claims that this index would reduce a multi-gigabyte scan to a particular
index size at 100K vehicles are projections and have not been verified.

## Top-K offender ranking

The saved run reported 7.631 ms before and 5.227 ms after, with the planner
using top-N heapsort in both cases. A bounded top-K heap has
O(n log K) sorting work after candidate rows are produced; total query cost
also includes scans, joins, and aggregation. Those timings came from the small
85-vehicle dataset and do not establish behavior at 100K vehicles.

## Single-vehicle trend

The documented primary key `(vehicle_id, summary_date)` is suitable for
vehicle/date-range lookups. A historical plan was recorded at approximately
1.9 ms. Confirm the index and plan against the current schema before relying
on this figure.

## Monthly aggregation

A historical comparison reported a raw aggregation over 2,280 rows at about
132.6 ms and a materialized-view lookup at about 0.104 ms for 17 result rows.
This is a small-data observation, not evidence of a 30-second baseline or
instantaneous behavior at larger scale. Materialized views trade refresh cost
and staleness for cheaper reads; refresh policy and uniqueness requirements
must be validated for the deployed workload.

## Pagination

Keyset pagination can avoid scanning and discarding a deep `OFFSET` when the
sort key has an appropriate index:

```sql
SELECT *
FROM vehicles
WHERE vin > :cursor
ORDER BY vin ASC
LIMIT 10;
```

This is a query-pattern advantage, not constant total response time regardless
of data shape. Confirm the API endpoint's ordering, index, cursor semantics,
and query plan when changing pagination.

## Scaling limits and next measurements

The commonly cited estimates in earlier drafts (for example 36.5M rollup rows,
11B telemetry events, or a specific monthly index footprint) are arithmetic
scenarios, not generated datasets or measured plans. They depend on event
density, retention, schema width, index overhead, compression, and query mix.
The 100K × 7-day database footprint estimate is separately documented in
[`scale-benchmark.md`](scale-benchmark.md) and is also an extrapolation.

Before making scale claims, capture current-schema `EXPLAIN (ANALYZE,
BUFFERS)` output and representative latency, memory, and storage measurements
on the intended dataset. Do not infer that a single Postgres node either
fails or meets the challenge target from these small-data plans.
