# Fleet Fuel, Idling & Utilisation Cost Intelligence

## Problem

Commercial fleets lose millions of dollars annually to engine idling and poor vehicle utilisation. Raw GPS and telemetry data is too noisy to surface this waste directly — it just says "vehicle X was at this coordinate doing 0 km/h at 14:02:11," a million times over. Fleet managers cannot see the financial impact of their operations from raw coordinates.

## Architecture

This product processes raw telemetry events into distinct trips and idle events, then calculates precise fuel and idling costs. It surfaces this intelligence via a React dashboard and an Agentic AI assistant.

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
# Fill in JWT_SECRET and GROQ_API_KEY (POSTGRES_URL defaults to local Postgres)
docker compose up --build
```

On first run, the `seeder` service automatically:
1. Creates 50 synthetic vehicles across 3 fleets
2. Generates 14 days of realistic telemetry (with deliberate duplicates to prove idempotency)
3. Runs the M4 segmentation engine
4. Runs the M5 cost rollup
5. Publishes 60 live events to Redpanda for the live-status demo

**Dashboard:** http://localhost:80  
**API Docs:** http://localhost:8000/docs  
**API health:** http://localhost:8000/health

> To connect to your existing Supabase dataset instead of the local Postgres, set `POSTGRES_URL=postgresql://user:pass@host:5432/postgres` in `.env`. The local Postgres service is skipped when an external URL is provided.

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `POSTGRES_URL` | PostgreSQL connection string | `postgresql://fleet_user:fleet_pass@postgres:5432/fleet_db` (local) |
| `JWT_SECRET` | Secret used for API authentication | — (required) |
| `GROQ_API_KEY` | API Key for the AI Agent (via Groq) | — (required for /chat) |
| `DEMO_USERNAME` | Login username for demo token | `admin` |
| `DEMO_PASSWORD` | Login password for demo token | — (required) |
| `REDIS_HOST` | Redis hostname | `redis` |
| `KAFKA_BOOTSTRAP_SERVERS` | Redpanda/Kafka bootstrap | `redpanda:9092` |
| `SEED_VEHICLES` | Number of vehicles to seed | `50` |
| `SEED_DAYS` | Days of historical data to seed | `14` |

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

## Known Limitations / Honest Disclosures

- **Demo scale:** The seeder generates 50 vehicles × 14 days by default (configurable via `SEED_VEHICLES` and `SEED_DAYS` in `.env`). Full 100K-vehicle scale is not run locally due to hardware constraints; the simulator architecture supports it via a `multiprocessing.Pool` sharding strategy (see `simulator/data_simulator.py` docstring).
- **VITE_* security:** Demo credentials in `VITE_DEMO_PASSWORD` are embedded in the built JS bundle — appropriate for a hackathon demo, not for production (where a login form + server-side session would replace this). Note that the dashboard actually uses a login form which does a POST to `/token`; the `VITE_DEMO_PASSWORD` is passed at build-time only to auto-fill the login form for convenience.
- **Container vulnerabilities:** The Trivy scan (`docs/trivy_scan_api.txt`) reports 44 high-severity findings — all in base OS packages. These are acknowledged technical debt; a production release would pin base images to hardened variants.
- **TLS:** Supabase connections enforce TLS by default; local Docker networking is plaintext (acceptable for local dev only).

## AI Tools & Open Source Declaration

### AI Assistance
- **Google Antigravity (Agentic IDE Assistant)** — Used for: architecture/module planning, scaffolding the segmentation state machine (M4) and cost calculation engine (M5), drafting documentation (ADRs, README), and test suite generation. All architectural decisions (storage choices, CAP/PACELC trade-offs, scoring methodology) were made and understood by the team.
- **Groq API / `llama3-8b-8192`** — Used as the underlying LLM for the M9 Agentic AI Layer.

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
- **OpenAI Python SDK** — AI agent tool-calling client
