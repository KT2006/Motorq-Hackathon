# Fleet Fuel, Idling & Utilisation Cost Intelligence

A local demo that turns synthetic vehicle telemetry into trip, idle, fuel-cost,
utilisation, and fleet-offender insights. All amounts and vehicle behavior are
based on documented simulator assumptions; they are not real fleet measurements
or proof of production-scale capacity.

## Quick start

```bash
git clone <repo>
cd <repo>
docker compose up --build
```

Open **http://localhost** and sign in with `admin` / `changeme`. Compose starts
the local services, waits for the one-shot seeder to finish, and then serves
the dashboard and API. No `.env` file or hosted database is required. These
known credentials and the local signing-key fallback are for this disposable
demo only; never expose the stack publicly or reuse them in deployment.

The default `balanced` seed creates 1,000 vehicles across 10 fleets with seven
days of route-consistent telemetry. It segments all vehicles and calculates
daily cost rollups, then publishes 60 live events to Redpanda. Dashboard
features work without an AI key; optional general assistant responses require
a Groq API key configured in `.env`.

Each synthetic day models a 10-hour shift with 2–5 trips, urban routes,
traffic stops, and between-shift refueling/recharging. Telemetry is sampled at
roughly one-minute intervals while moving, with additional trip and idle
boundary events. Reference fuel efficiencies are petrol 12 km/L, diesel
15 km/L, hybrid 18 km/L, and EV 5.5 km/kWh. Cost assumptions are petrol/hybrid
₹103/L, diesel ₹92/L, and electricity ₹8/kWh. Utilisation is measured against
a 600-minute shift. These are fixed illustrative values, not live prices or
validated savings estimates. See [`docs/algorithms.md`](docs/algorithms.md).

**Dashboard:** http://localhost

**API docs:** http://localhost:8000/docs
**API health:** http://localhost:8000/health

The overview defaults to the latest seven available data days. The API also
supports explicit date ranges and monthly reporting.

## Configuration

Compose intentionally overrides the API and seeder database URL to use the
local Postgres service. The demo does not connect to Supabase or another hosted
database. Values below describe local Compose behavior; application-only runs
may require explicit configuration.

| Variable | Purpose | Local Compose default |
|---|---|---|
| `POSTGRES_URL` | PostgreSQL connection string | Forced to local `postgres` service |
| `JWT_SECRET` | API token signing key | Local demo fallback; replace outside local demo |
| `DEMO_USERNAME` / `DEMO_PASSWORD` | Demo login | `admin` / `changeme` |
| `GROQ_API_KEY` | Optional external assistant API key | Unset |
| `GROQ_MODEL` | Model used by optional assistant | `openai/gpt-oss-20b` |
| `REDIS_HOST` | Live-status cache | `redis` |
| `KAFKA_BOOTSTRAP_SERVERS` | Redpanda/Kafka endpoint | `redpanda:9092` |
| `SEED_MODE` | Seed profile | `balanced` |
| `SEED_VEHICLES`, `SEED_DAYS` | Optional profile overrides | Profile defaults |
| `SEED_SEGMENT_SAMPLE` | Number segmented in `full` mode | `500` |

`balanced` means 1,000 vehicles × 7 days; `demo` means 50 × 14 days; `full`
means 100,000 × 1 day. The `full` profile has **not been run and verified** and
is not the judge-facing default. It is not a sparse substitute for 100K × 7
detailed days. Avoid it on constrained hardware; see
[`docs/scale-benchmark.md`](docs/scale-benchmark.md) for measured storage and
clearly labeled estimates.

## Disposable data lifecycle

The local Postgres, Redis, and Redpanda runtime data use temporary filesystems.
Stop the stack and remove Compose resources with:

```bash
docker compose down -v
```

The next `docker compose up --build` starts with empty local stores and seeds
fresh data. Do not use external database URLs for this disposable workflow.

## Tests and performance evidence

```bash
pip install -r services/segmentation/requirements.txt pytest pytest-cov psycopg2-binary
pytest --cov=services/segmentation --cov-report=term-missing tests/
```

A Locust smoke test can be run against a started stack:

```bash
locust -f locustfile.py --host http://localhost:8000 --users 10 --spawn-rate 2 --run-time 30s --headless
```

This API smoke test is distinct from the streaming throughput target. Current
evidence and limitations are documented in
[`docs/load-test-results.md`](docs/load-test-results.md) and
[`docs/scale-benchmark.md`](docs/scale-benchmark.md).

## Documentation

| Document | Contents |
|---|---|
| [`docs/solution.md`](docs/solution.md) | Solution narrative, requirement status, and submission gaps |
| [`docs/architecture.md`](docs/architecture.md) | System diagrams, data flow, schema, and failure behavior |
| [`docs/algorithms.md`](docs/algorithms.md) | Segmentation and cost formulas |
| [`docs/adrs.md`](docs/adrs.md) | Architecture decisions |
| [`docs/security.md`](docs/security.md) | Implemented controls, limitations, and data lifecycle |
| [`docs/query-optimisation.md`](docs/query-optimisation.md) | Historical query-plan evidence and projection caveats |
| [`docs/load-test-results.md`](docs/load-test-results.md) | API smoke-load runs and caveats |
| [`docs/scale-benchmark.md`](docs/scale-benchmark.md) | Measured data size, estimates, and separate streaming result |
| [`docs/requirement-matrix.md`](docs/requirement-matrix.md) | Requirement traceability and status |
| [`docs/openapi.json`](docs/openapi.json) | OpenAPI specification |

## Requirement status at a glance

| Area | Status | Evidence / limitation |
|---|---|---|
| Local weekly demo | **Verified locally** | Fresh Compose run: 1,000 vehicles, 7,000 daily cost rows, analytics for 1,000; dashboard and API returned data. |
| 100K-vehicle minimum | **Not verified** | Full profile exists but was not run; default is 1,000 vehicles. |
| 100K events/sec and 3× burst NFR | **Not met in short local test** | About 8.2K events/sec end-to-end; no sustained or burst test. |
| 80% test coverage | **Not met** | Saved focused report shows 35% across measured modules. |
| Cloud deployment / high availability | **Planned, unverified** | Kubernetes and Terraform artifacts are scaffolding; not deployed or tested. |
| Security hardening | **Partial** | JWT, fleet filters, validation, and rate limits exist; demo credentials, plaintext networking, and an older image scan are caveats. |

See [`docs/requirement-matrix.md`](docs/requirement-matrix.md) for details.

## AI tools and open-source declaration

### AI assistance

- **Google Antigravity (Agentic IDE Assistant):** Used for architecture/module
  planning, segmentation and cost-engine scaffolding, documentation drafts,
  and test generation. The team is responsible for understanding and validating
  the submitted work.
- **Groq API / `openai/gpt-oss-20b`:** Optional service for generating assistant
  responses from database-backed fleet context.

### Key open-source libraries

FastAPI, Uvicorn, psycopg2, kafka-python, redis-py, Pydantic, SlowAPI, pytest,
pytest-cov, Locust, React, Vite, Recharts, and the OpenAI-compatible Python SDK.
