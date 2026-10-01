# Architecture Diagrams

> These Mermaid diagrams describe the current local demo. Cloud diagrams and
> scale figures should not be read as deployed or benchmarked production claims.

---

## 1. C4 Context Diagram

```mermaid
C4Context
    title Fleet Fuel, Idling & Utilisation Cost — System Context

    Person(fm, "Fleet Manager", "Reviews idling, costs, utilisation, and vehicle analytics.")

    System(sys, "Fleet Intelligence Platform", "Seeds synthetic data, computes fleet costs, and serves dashboard analytics.")

    System_Ext(groq, "Groq LLM API (optional)", "Generates assistant responses using compact SQL-derived context.")

    Rel(fm, sys, "Views fleet and vehicle analytics", "HTTP / React")
    Rel(sys, groq, "Optional prompt and SQL-derived context", "HTTPS / REST")
```

---

## 2. Batch Seed and Live-Event Data Flow

```mermaid
sequenceDiagram
    participant COMPOSE as Docker Compose
    participant SEED as One-shot seeder
    participant SIM as Route simulator
    participant DB as Local TimescaleDB
    participant RP as Redpanda
    participant ING as Ingestion consumer
    participant CACHE as Redis
    participant API as FastAPI
    participant UI as React dashboard

    COMPOSE->>SEED: Start after Postgres and Redpanda health checks
    SEED->>DB: Insert fleets and vehicles
    SEED->>SIM: Generate the selected seed profile
    SIM->>DB: Bulk-write telemetry
    SEED->>DB: Segment trips/idles and roll up daily costs
    SEED->>RP: Publish 60 sample live events
    SEED-->>COMPOSE: Exit successfully after publish
    Note over RP,ING: Consumer processes live events asynchronously; seeding does not wait for Redis updates
    RP->>ING: Deliver events from telemetry topic
    ING->>DB: Validate and idempotently persist
    ING->>CACHE: Update latest status per vehicle
    COMPOSE->>API: Start after successful seed
    COMPOSE->>UI: Start after API health check
    UI->>API: Request fleet summary, offenders, or vehicle detail
    API->>DB: Read derived analytics
    API-->>UI: Return dashboard data
```

The startup seed writes historical telemetry directly to Postgres; Redpanda
is a separate live-event path. The configured balanced profile is 1,000
vehicles × 7 days; the verified run produced 7,000 daily cost rows. Other
profile sizes are described in the README and scale report.

---

## 3. Segmentation State Machine

```mermaid
stateDiagram-v2
    [*] --> NOT_IN_TRIP

    NOT_IN_TRIP --> DRIVING : TRIP_START event\nOR speed > 3 km/h AND ignition=ON\n[Open new trip record]

    NOT_IN_TRIP --> NOT_IN_TRIP : speed <= 3 AND ignition=ON\n[Track depot idle]

    DRIVING --> NOT_IN_TRIP : TRIP_END event\nOR ignition=OFF\n[Close trip, emit record]

    DRIVING --> IN_TRIP_IDLE : speed <= 3 AND ignition=ON\n[Open idle_event: in_trip]

    IN_TRIP_IDLE --> DRIVING : speed > 3 km/h\n[Close idle if duration >= 60s, resume trip]

    IN_TRIP_IDLE --> NOT_IN_TRIP : idle > 900s\nOR TRIP_END\nOR ignition=OFF\n[Close idle + close trip]
```

---

## 4. Entity-Relationship Diagram (Key Tables)

```mermaid
erDiagram
    fleets {
        UUID fleet_id PK
        TEXT fleet_name
        TEXT fleet_type
        TEXT region
    }
    vehicles {
        UUID vehicle_id PK
        CHAR vin UK
        UUID fleet_id FK
        TEXT make
        TEXT model
        TEXT fuel_type
    }
    telemetry_events {
        BIGSERIAL event_id PK
        CHAR vin
        TIMESTAMPTZ ts
        FLOAT speed_kmh
        BOOL ignition_status
        FLOAT fuel_level_pct
        TEXT evt
        BIGINT seq
    }
    trips {
        UUID trip_id PK
        CHAR vin
        TIMESTAMPTZ start_ts
        TIMESTAMPTZ end_ts
        NUMERIC distance_km
        NUMERIC duration_min
    }
    idle_events {
        UUID idle_id PK
        CHAR vin
        UUID trip_id FK
        TIMESTAMPTZ start_ts
        TIMESTAMPTZ end_ts
        NUMERIC duration_min
        TEXT idle_type
    }
    cost_summary_daily {
        UUID vehicle_id PK,FK
        DATE summary_date PK
        NUMERIC total_idle_min
        NUMERIC idle_cost
        NUMERIC fuel_cost
        NUMERIC utilisation_pct
    }
    agent_logs {
        BIGSERIAL log_id PK
        TIMESTAMPTZ created_at
        TEXT user_question
        JSONB tool_calls_json
        TEXT final_answer
    }
    audit_log {
        BIGSERIAL log_id PK
        TIMESTAMPTZ created_at
        TEXT user_sub
        TEXT action
        TEXT resource
        TEXT resource_id
        TEXT ip_address
        JSONB details
    }

    fleets ||--o{ vehicles : "has"
    vehicles ||--o{ trips : "makes"
    vehicles ||--o{ idle_events : "generates"
    vehicles ||--o{ cost_summary_daily : "summarised in"
    trips ||--o{ idle_events : "contains"
```

---

## 5. Local Deployment Topology

The local Compose stack is single-node. The diagrams are split by traffic
path so service dependencies remain easy to follow.

### Browser request path

```mermaid
flowchart TB
    BROWSER["Browser<br/>localhost:80"] --> DASH["Dashboard<br/>Nginx"]
    DASH -->|"HTTP /api proxy"| API["FastAPI<br/>localhost:8000"]
    API --> DB[("PostgreSQL<br/>TimescaleDB")]
    API --> CACHE[("Redis<br/>live status")]
    API -. optional .-> GROQ["Groq API"]
```

### Telemetry ingestion path

```mermaid
flowchart LR
    PRODUCER["Seeder<br/>60 demo events"] --> BROKER["Redpanda<br/>telemetry topic"]
    BROKER --> CONSUMER["Ingestion consumer<br/>batch size 5,000"]
    CONSUMER --> DATABASE[("PostgreSQL<br/>TimescaleDB")]
    CONSUMER --> STATUS[("Redis<br/>live status")]
```

The API and startup seeder connect directly to Postgres; the API reads live
status directly from Redis. PgBouncer is included and health-checked by
Compose, but the current API URL does not route through it. Groq is external
and optional. Kubernetes/Terraform files are unverified scaffolding, not part
of this local deployment.

---

## 6. Failure Sequence — Consumer Crash & Recovery

```mermaid
sequenceDiagram
    participant RP as Redpanda
    participant CON as Ingestion Consumer
    participant PG as PostgreSQL
    participant RD as Redis
    participant DLQ as telemetry-dlq topic

    RP->>CON: Poll records (up to configured batch)
    loop For each record in the polled batch
        CON->>CON: Parse JSON and validate schema
        alt Invalid record
            CON->>DLQ: Attempt to publish original record + error
            Note over CON,DLQ: Send failures are logged; processing continues
        else Valid record
            CON->>PG: Add event to batch insert
        end
    end
    opt At least one valid record
        CON->>PG: Persist valid events; commit database transaction
        CON->>RD: Update live-status cache
    end
    alt Database or Redis operation fails
        CON->>CON: Roll back open transaction; reconnect if needed
        Note over RP,CON: Offsets are not committed; records can be replayed
        Note over PG,RD: If Postgres had committed before Redis failed, the replayed DB inserts are idempotent
    else Batch handling succeeds
        CON->>RP: Commit offsets
    end
```

Postgres insertion is committed before the Redis update, so the stores are
not atomic. On a Redis failure, Kafka offsets remain uncommitted and replayed
event inserts are idempotent, but the Redis update must still succeed before
offsets are committed. A dead-letter send failure is a known gap: the helper
logs that failure while the consumer can still advance the offset. This local
implementation does not promise zero data loss under every failure mode.

---

## 7. AI Assistant Context-Grounded Response Flow

```mermaid
sequenceDiagram
    participant U as User (Dashboard)
    participant API as FastAPI /chat
    participant DB as PostgreSQL
    participant LLM as Groq LLM
    participant AUDIT as audit_log / agent_logs

    U->>API: POST /chat {query, from_date, to_date}
    API->>API: verify JWT, extract fleet_id
    API->>AUDIT: Write selected audit event
    alt Fleet-data question
        API->>DB: Aggregate costs, idle time, utilisation for requested dates
        DB-->>API: Authoritative metrics
        opt Ranking or vehicle-list question
            API->>DB: Select highest idle-cost vehicles for same dates and fleet
            DB-->>API: Vehicle rows
        end
        API->>LLM: Authoritative database context + user prompt
        LLM-->>API: Context-grounded response
    else General question
        API->>LLM: User prompt
        LLM-->>API: General response
    end

    API->>AUDIT: Write assistant question and answer to agent_logs
    API-->>U: {answer, tool_calls: []}
```
