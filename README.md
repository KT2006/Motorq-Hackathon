# Fleet Fuel, Idling & Utilisation Cost Intelligence

## Problem
Commercial fleets lose millions of dollars annually to engine idling and poor vehicle utilisation. However, raw GPS and telemetry data is too noisy to surface this waste directly. Fleet managers cannot see the financial impact of their operations from raw coordinates.

## Architecture
This product processes raw telemetry events into distinct trips and idle events, then calculates precise fuel and idling costs. It surfaces this intelligence via a React dashboard and an Agentic AI assistant.

**Pipeline:**
Simulator → Supabase (`telemetry_events`) → Segmentation Engine (M4) → Cost Engine (M5) → FastAPI Layer (M7) → React Dashboard & AI Agent (M8/M9)

## Quick Start
1. Clone this repo: `git clone ...`
2. Copy the example environment variables: `cp .env.example .env`
3. Fill in your `.env` with your Supabase connection string and Groq/OpenAI API key.
4. Run the full stack with Docker Compose:
   ```bash
   docker compose up --build
   ```
5. **Dashboard:** Available at [http://localhost:80](http://localhost:80)
6. **API Docs:** Available at [http://localhost:8000/docs](http://localhost:8000/docs)

*Note: The seeded dataset lives in our hosted Supabase instance. By providing the correct `POSTGRES_URL` in `.env`, your local Docker containers will securely connect to it.*

## Environment Variables

| Variable | Description | Example |
|---|---|---|
| `POSTGRES_URL` | Supabase Postgres connection string | `postgresql://user:password@host:5432/postgres` |
| `JWT_SECRET` | Secret used for API authentication | `super-secret-hackathon-key` |
| `GROQ_API_KEY` | API Key for the AI Agent (via Groq) | `gsk_...` |

## Running Tests
Ensure dependencies are installed (`pip install -r services/segmentation/requirements.txt pytest pytest-cov locust psycopg2-binary`).
- **Unit & Integration Tests:** `pytest --cov=services/segmentation --cov-report=term-missing tests/`
  - *Note: Test coverage (detailed in `/docs/coverage-report.txt`) strictly targets our core correctness-critical logic (the M4 segmentation state machine and M5 cost calculation algorithms). Peripheral glue code, database connectors, and API routing have lighter coverage due to time constraints.*
- **Load Tests:** `locust -f locustfile.py --host http://localhost:8000 --users 50 --spawn-rate 10 --run-time 60s --headless` (See `/docs/load-test-results.md` for results)

## Known Issues / Scope Decisions
- **Ingestion Path:** Ingestion is currently a direct write from the simulator to Supabase rather than a Kafka/Redpanda streaming path due to hackathon time constraints (see ADR-04 for reasoning).
- **Idempotency Proof:** Despite skipping a literal stream broker, we proved the ingestion idempotency constraints required for a real stream. The `ON CONFLICT DO NOTHING` unique index on `(vin, ts, seq)` successfully drops duplicates and orders late arrivals, as proven in our integration tests.

## AI Tools & Open Source Declaration

### AI Assistance
- **Google Antigravity (Agentic IDE Assistant)** — Used for: architecture/module planning discussions, scaffolding the segmentation state machine (M4) and cost calculation engine (M5), drafting documentation (ADRs, this README), and test suite generation. All architectural decisions (storage choices, CAP/PACELC trade-offs, scoring methodology) were made and understood by the team; AI assistance was used to accelerate implementation and documentation, not to make design decisions independently.
- **Groq API / `openai/gpt-oss-120b`** — Used as the underlying LLM for the M9 Agentic AI Layer to power natural language querying over our fleet dataset.

### Key Open Source Libraries
- **FastAPI / Uvicorn** — Backend API framework and ASGI server
- **psycopg2** — PostgreSQL database connectivity
- **pytest, pytest-cov** — Unit and integration testing
- **Locust** — Load testing
- **React / Vite** — Frontend dashboard framework
- **Recharts** — Dashboard data visualization
- **OpenAI Python SDK** — API client for agentic tool-calling
- **Supabase** — Managed PostgreSQL 17 hosting
