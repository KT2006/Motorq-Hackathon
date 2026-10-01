# M11: Testing & Load Validation Results

## 1. Unit Tests
- **Segmentation (M4)**: Created `tests/test_segmentation.py` with 5 passing tests covering:
  - Clean trip detection
  - In-trip idle detection (stops > 60s)
  - Short stop filtering (stops < 60s)
  - Depot idle (no active trip)
  - Graceful handling of edge cases (no ignition-off marker)
- **Cost Calculation (M5)**: Created `tests/test_cost_calc.py` with 4 passing tests covering:
  - Pure math logic for fuel and idle cost
  - Utilisation percentages
  - A test concretely demonstrating the edge-case where the weighted-score flags a vehicle that a naive threshold misses.

## 2. Integration Test (Idempotency Proof)
- Created `tests/test_ingestion_idempotency.py` which connects to the Postgres database.
- It validates that inserting a duplicate telemetry event (same `vin`, `ts`, `seq`) correctly results in a no-op due to our `ON CONFLICT (vin, ts, seq) DO NOTHING` rule.
- It also validates that events arriving out-of-order still return correctly due to our `ORDER BY ts ASC, seq ASC` queries.

## 3. Load Test Results
A locust script was run with 50 concurrent users spawning at a rate of 10/sec, targeting `/fleet/offenders` and `/fleet/summary`.

**Locust Summary Output:**
```
Type     Name                                                                  # reqs      # fails |    Avg     Min     Max    Med |   req/s
--------||-------|-------------|-------|-------|-------|-------|--------|-----------
GET      /fleet/offenders?limit=10&from_date=2026-08-01&to_date=2026-08-31    1899       *1806(95.10%) |     63       1    2237      2 |   96.14
GET      /fleet/summary?month=2026-08-01                                       601       *601(100.00%) |      4       1     107      2 |   30.43
POST     /token                                                                 50        0(0.00%) |     15       4      25     13 |    2.53
--------||-------|-------------|-------|-------|-------|-------|--------|-----------
         Aggregated                                                           2550       *2407(94.39%) |     48       1    2237      2 |  129.10
```

**Interpretation:** This run is **not a successful 129 req/s API capacity
result**. The aggregate includes 94.39% failures, mostly rate-limited
responses; the reported request rate counts failed requests too. It shows that
the limiter rejected excess traffic in that run, not that the application
served that load successfully. The run was not a clean capacity test, and the
low successful-response median does not establish tail latency or behavior
under a representative workload.

## Local Compose Smoke Load (2026-10-01)

After a fresh balanced-profile seed, Locust ran for 30 seconds with 10 users
spawning at 2 users/second against the live API. It completed 237 requests
with no failures: 7.98 requests/sec aggregate, 23 ms average response time,
and 38 ms p95 (43 ms p99). This limited local smoke run is below the 200 ms
API p95 target, but does not meet the requirement for sustained or scale
testing. It is not a 50-user soak or an ingestion-throughput test; the earlier
run above is separate and had a high failure rate.
