# Fleet Fuel, Idling & Utilisation Cost Intelligence

## Problem

Commercial fleets incur avoidable operating costs through engine idling and poor vehicle utilisation. Raw GPS and telemetry data is too noisy to surface this waste directly — it just says "vehicle X was at this coordinate doing 0 km/h at 14:02:11," a million times over. Fleet managers need to see the financial impact of their operations from raw coordinates, expressed in Indian rupees (INR).

## Architecture

This product processes raw telemetry events into distinct trips and idle events, then calculates precise fuel and idling costs. It surfaces this intelligence via a React dashboard and an AI assistant that receives database-backed fleet context before generating responses.

**Full streaming pipeline:**

```
Simulator (data_simulator.py)
  → Redpanda / Kafka (topic: telemetry)
  → Ingestion Consumer (validate + dedup + batch write)
      ├─→ PostgreSQL: telemetry_events (raw)
      └─→ Redis: vehicle:{vin}:status (live status cache)
  → Segmentation Engine (M4, state machine)     ← trips + idle_events
  → Cost Engine (M5, daily rollup + top-K)      ← cost_summary_daily
  → FastAPI Layer (M7, JWT + rate limiting)
  → React Dashboard (M8) + AI Agent (M9)
```

**Polyglot storage:**
| Store | What lives here | CAP choice |
|---|---|---|
| PostgreSQL (TimescaleDB) | trips, idle_events, cost_summary_daily, fleets, vehicles | CP — billing-adjacent numbers must be consistent |
| Redis | `vehicle:{vin}:status` live position cache | AP — sub-ms reads, ephemeral, TTL-managed |
| Redpanda | `telemetry` topic (streaming ingest) | AP — high throughput, at-least-once delivery |

## Quick Start

```bash
git clone <repo>
cd <repo>
cp .env.example .env
# Fill in JWT_SECRET, GROQ_API_KEY, and DEMO_PASSWORD
docker compose up --build
```

On first run, the `seeder` service automatically:
1. Creates 50 synthetic vehicles across 3 fleets
2. Generates 14 days of synthetic telemetry (with deliberate duplicates to prove idempotency)
3. Runs the M4 segmentation engine
4. Runs the M5 cost rollup
5. Publishes 60 live events to Redpanda for the live-status demo

The demo profile models a 10-hour scheduled shift with 2-4 trips per vehicle per
day, typically 20-40 km per trip and 25-40 km/h target speeds. Fuel/SOC
consumption uses synthetic reference assumptions (petrol 12 km/L, diesel
15 km/L, hybrid 18 km/L, EV 5.5 km/kWh; 50 L tank and 60 kWh battery).
These are illustrative demo values, not measurements from real vehicles.
Utilisation is calculated against the 600-minute shift. Existing database
volumes are not automatically reseeded; use a fresh demo database to see the
updated profile.

Cost rollups use INR reference prices: petrol/hybrid ₹103 per litre, diesel
₹92 per litre, and electricity ₹8 per kWh. These are fixed synthetic demo
assumptions; the API and dashboard treat cost values as INR and do not perform
currency conversion.

**Dashboard:** http://localhost:80  
**API Docs:** http://localhost:8000/docs  
**API health:** http://localhost:8000/health

The fleet overview defaults to the latest month with available cost data, so
the dashboard remains populated even when the stack is first started on the
first day of a new month. The API also accepts an explicit `month` query
parameter when a specific reporting month is needed.

> To connect to your existing Supabase dataset instead of the local Postgres, set `POSTGRES_URL=postgresql://user:pass@host:5432/postgres` in `.env`. The local Postgres service is skipped when an external URL is provided.

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `POSTGRES_URL` | PostgreSQL connection string | `postgresql://fleet_user:fleet_pass@postgres:5432/fleet_db` (local) |
| `JWT_SECRET` | Secret used for API authentication | — (required) |
| `GROQ_API_KEY` | API key for general (non-fleet-data) assistant chat via Groq | — |
| `GROQ_MODEL` | Groq model used by the AI Agent | `openai/gpt-oss-20b` |
| `DEMO_USERNAME` | Login username for demo token | `admin` |
| `DEMO_PASSWORD` | Login password for demo token | — (required) |
| `REDIS_HOST` | Redis hostname | `redis` |
| `KAFKA_BOOTSTRAP_SERVERS` | Redpanda/Kafka bootstrap | `redpanda:9092` |
| `SEED_MODE` | `demo` (50 vehicles × 14 days, fast) or `full` (100K vehicles × 1 day, multiprocessed) | `demo` |
| `SEED_VEHICLES` | Number of vehicles to seed (overrides SEED_MODE default) | `50` / `100000` |
| `SEED_DAYS` | Days of historical data to seed | `14` / `1` |
| `SEED_SEGMENT_SAMPLE` | In full mode, how many vehicles to run the segmentation engine over | `500` |

### Running at 100K-vehicle scale

```bash
# In .env, set:
SEED_MODE=full

# Then bring up the stack — seeder will use all CPU cores (~10-20 min on 8 cores):
docker compose up --build
```

The multiprocessed simulator shards 100K vehicles across all available CPU cores (one worker per core). Each worker connects independently to Postgres and writes in batches of 50K events. On an 8-core machine, 100K vehicles × 1 day (~100M events) takes approximately 10–20 minutes.

## Running Tests

```bash
pip install -r services/segmentation/requirements.txt pytest pytest-cov psycopg2-binary
pytest --cov=services/segmentation --cov-report=term-missing tests/
```

Load tests:
```bash
locust -f locustfile.py --host http://localhost:8000 --users 50 --spawn-rate 10 --run-time 60s --headless
```
See `/docs/load-test-results.md` for results.

## Documentation

| Doc | Contents |
|---|---|
| [`docs/algorithms.md`](docs/algorithms.md) | M4 segmentation state machine + M5 cost scoring with complexity analysis |
| [`docs/adrs.md`](docs/adrs.md) | Architecture Decision Records (storage CAP choices, rules-vs-ML, idempotency) |
| [`docs/architecture.md`](docs/architecture.md) | C4, data-flow, ERD, deployment, state-machine, failure-sequence diagrams |
| [`docs/security.md`](docs/security.md) | STRIDE model, JWT/rate-limiting, data lifecycle |
| [`docs/query-optimisation.md`](docs/query-optimisation.md) | EXPLAIN ANALYZE before/after with index improvements |
| [`docs/load-test-results.md`](docs/load-test-results.md) | Locust load test results |
| [`docs/openapi.json`](docs/openapi.json) | Full OpenAPI 3.1 spec |

## Benchmark Environment & Reality Check

| Parameter | Default Value | Configurable Via |
|-----------|--------------|------------------|
| Seed vehicles | 50 (demo) / 100K (full) | `SEED_MODE` env var |
| Seed days | 14 (demo) / 1 (full) | `SEED_DAYS` env var |
| Stream events | 60 | `SEED_STREAM_EVENTS` env var |

*Note: The multiprocessed simulator has been implemented and verified to generate the correct event volume. A full 100K-vehicle × 1-day run (~103M events) requires ~10–20 minutes on an 8-core machine with sufficient disk space (~4–6 GB). Due to hardware and time constraints, a full end-to-end run was not completed during development.*

## Known Limitations / Honest Disclosures

- **Demo scale (default):** The seeder defaults to 50 vehicles × 14 days for fast local dev. Set `SEED_MODE=full` to seed 100K vehicles × 1 day using all CPU cores.
- **Full mode segmentation:** In full mode, the segmentation + cost engine runs over a configurable sample (default 500 vehicles) — raw telemetry for all 100K vehicles is written to Postgres, but running M4 over 100K VINs serially would take hours.
- **TimescaleDB:** TimescaleDB is a hard dependency required for the hypertable partitioning on telemetry events.
- **Horizontal Scaling:** Single Postgres instance (SPOF). Single Redis instance. True horizontal scaling (read replicas, Redis cluster) is not implemented.
- **Test Coverage:** Currently at ~42%, not the 80% target.
- **Container vulnerabilities:** The Trivy scan reports 44 high-severity findings in base OS packages.
- **TLS:** Local Docker networking is plaintext.

## AI Tools & Open Source Declaration

### AI Assistance
- **Google Antigravity (Agentic IDE Assistant)** — Used for: architecture/module planning, scaffolding the segmentation state machine (M4) and cost calculation engine (M5), drafting documentation (ADRs, README), and test suite generation. All architectural decisions (storage choices, CAP/PACELC trade-offs, scoring methodology) were made and understood by the team.
- **Groq API / `openai/gpt-oss-20b`** — Used to generate M9 assistant responses from database-backed fleet context (`GROQ_MODEL` can override it).

### Key Open Source Libraries
- **FastAPI / Uvicorn** — Backend API framework
- **psycopg2** — PostgreSQL connectivity
- **kafka-python** — Redpanda/Kafka producer + consumer
- **redis-py** — Redis live status cache
- **pydantic** — Event schema validation in ingestion consumer
- **slowapi** — Rate limiting middleware
- **pytest, pytest-cov** — Unit and integration testing
- **Locust** — Load testing
- **React / Vite** — Frontend dashboard
- **Recharts** — Dashboard data visualization
- **OpenAI Python SDK** — OpenAI-compatible client for Groq general chat
