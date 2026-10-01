# Scale and Performance Evidence

This document separates three different things: the default judge-demo seed,
database-size extrapolations, and streaming-ingestion measurements. A seed
writer's event rate is not a streaming-ingestion benchmark.

## Verified local dataset

On 2026-10-01, the local Compose stack completed the balanced seed:

| Measurement | Observed |
|---|---:|
| Vehicles | 1,000 |
| Seeded history | 7 days |
| Telemetry rows after the 60 live demo events | 969,819 |
| Daily cost rows | 7,000 (1,000 vehicles × 7 dates) |
| Vehicles represented in cost summaries | 1,000 |
| Telemetry hypertable size | 310,247,424 bytes (~296 MiB) |
| Whole database size | 339,819,543 bytes (~324 MiB) |
| Seed simulator output | 969,759 events in 14.4 s (~67,118 events/s) |

The simulator rate combines generation and direct database writes. It does not
include Redpanda ingestion and must not be compared to the streaming NFR.

At the time of that run, Docker exposed 3.8 GiB to the stack, Postgres used
about 1.28 GiB, and the host reported about 17 GiB free. These are machine-
specific snapshots, not fixed resource requirements.

## Storage estimates for larger dense profiles

The estimate below scales from the measured 1,000-vehicle × 7-day run. It
assumes comparable events per vehicle and similar PostgreSQL/index overhead;
real use varies with data shape, index growth, maintenance, and temporary
write/WAL space. The database used tmpfs locally, so its footprint consumes
Docker memory rather than persistent host disk.

| Profile | Estimated telemetry rows | Estimated hypertable | Estimated whole DB | Status |
|---|---:|---:|---:|---|
| 1,000 × 7 days (observed) | ~0.97M | ~0.31 GB | ~0.34 GB | **Verified** |
| 50,000 × 7 days, same density | ~48.5M | ~15.5 GB | ~17 GB | **Extrapolated; not run** |
| 100,000 × 1 day, same density | ~13.9M | ~4.4 GB | ~4.9 GB | **Extrapolated; full profile not run** |
| 100,000 × 7 days, same density | ~97M | ~31 GB | ~34 GB | **Extrapolated; not run** |

These are base database estimates, not safe Docker limits. Peak memory and
temporary space can be higher. The estimated 100,000 × 7-day dense run is not
appropriate for the development laptop measured above. A larger borrowed
machine may be suitable only after checking its free SSD, Docker memory limit,
and ability to host the complete database plus headroom. The full seed also
uses detailed telemetry and analytics only for a configurable sample.

A sparse 50K/100K profile has been discussed but is **not implemented or
validated**. Sparse data could reduce storage substantially, but must preserve
coherent trips and daily analytics before it can count as meaningful scale
evidence.

## Streaming ingestion result (separate workload)

A short local test published 10,000 unique, schema-valid events across 1,000
VINs to Redpanda. All 10,000 reached `telemetry_events`; the measured producer
rate was 14,894 events/s and end-to-end publish-to-database rate was 8,234
events/s, with about 0.54 seconds to drain after producer flush.

This was a short functional check—not a sustained run, a five-minute 3× burst,
or a 100K-events/sec test. It is approximately 12× below the 100,000
events/sec target. The burst/no-loss NFR remains **unverified**.

## Acceptance status and next evidence

| Requirement | Current status | Evidence needed |
|---|---|---|
| At least 100,000 simulated vehicles | **Not verified** | Complete a fresh 100K-vehicle generation run on suitable hardware; record vehicle count and analytics coverage. |
| 100,000 events/sec sustained | **Not met by current local result** | Reproducible load run that measures accepted/persisted rate, latency, lag, failures, and duration. |
| 3× burst for 5 minutes without data loss | **Not verified** | Explicit burst workload, end-offset/count reconciliation, and failure report. |
| API p95 < 200 ms | **Partially evidenced** | A separate 30-second local API smoke load measured p95 38 ms; this is not a scale or soak test. See [`load-test-results.md`](load-test-results.md). |

Do not use projected values as completed results. Record hardware and Docker
limits, exact commands/profile, event counts, storage before/after, runtime,
peak memory, failures, and cleanup outcome for any future scale run.
