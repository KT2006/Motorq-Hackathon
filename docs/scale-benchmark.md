# Scale Benchmark & Architecture Blueprint

## Current Local Performance Baseline
To establish a baseline for the ingestion pipeline, we configured a stress-test against the local Docker Compose stack:
- **Redpanda:** `telemetry` topic running with 9 partitions.
- **Ingestion Tier:** 4 Python worker containers (`docker compose up --scale ingestion=4`) utilizing `psycopg2.extras.execute_values`.
- **Database:** TimescaleDB local container (Postgres 16, `synchronous_commit=off`).

**Test Execution:** We bypassed the synthetic O(n) simulator and blasted 1,000,000 valid JSON telemetry events directly into Redpanda using a custom multiprocessing load generator. 
*Note: This payload used repetitive synthetic data (fixed timestamp, lat/lon, speed) to specifically test raw database I/O and queue throughput, not real-world telemetry diversity.*

- **Generation:** 1,000,000 events pushed to Redpanda.
- **Ingestion:** The 4 Python workers processed and inserted these events into the TimescaleDB hypertable at a sustained, measured rate of **~5,275 events per second**.

## Path to 100,000 Events / Sec (Target Architecture)
Our local test establishes a functional baseline of ~5.3K events/sec on a single node running all stack components. This represents the ceiling for this specific local hardware configuration.

To achieve the 100K target in a production environment, the system requires horizontal scaling:
1. **Redpanda Cluster:** A multi-broker cluster with the topic expanded to 50+ partitions (keyed by `vin`).
2. **Ingestion Tier:** A Kubernetes (EKS/GKE) deployment running dozens of ingestion pods to parallelize the workload, or a rewrite of the Python consumer in a highly concurrent language like Go or Rust to maximize per-node throughput.
3. **Database Tier:** A managed TimescaleDB instance with high IOPS storage and bulk `COPY` inserts.

The 100K/sec figure is our architectural target. The system's decoupled design (Redpanda -> Worker -> TimescaleDB) provides the necessary foundation for this scale when deployed on distributed infrastructure.
