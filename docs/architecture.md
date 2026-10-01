# Architecture Diagrams

> All diagrams are rendered as Mermaid. They are embedded in the Solution Document and in this file for reference.

---

## 1. C4 Context Diagram

```mermaid
C4Context
    title Fleet Fuel, Idling & Utilisation Cost — System Context

    Person(fm, "Fleet Manager", "Monitors idling waste, fuel costs, and utilisation. Acts on AI recommendations.")
    Person(admin, "Fleet Admin", "Manages vehicle/driver data, views audit logs.")

    System(sys, "Fleet Intelligence Platform", "Ingests raw telemetry, computes cost, surfaces insight via dashboard and AI agent.")

    System_Ext(telematics, "Vehicle Telematics Devices", "GPS + OBD-II dongles on every vehicle. Emit position, speed, fuel, ignition events.")
    System_Ext(groq, "Groq LLM API", "Writes answers using compact, authoritative fleet context queried from PostgreSQL.")
    System_Ext(supabase, "Supabase (optional)", "Managed Postgres hosting for production deployments.")

    Rel(telematics, sys, "Streams raw telemetry events", "Kafka/Redpanda")
    Rel(fm, sys, "Views dashboard, queries AI agent", "HTTPS / React")
    Rel(admin, sys, "Manages fleet data", "HTTPS / React")
    Rel(sys, groq, "Sends fleet context and user prompt", "HTTPS / REST")
    Rel(sys, supabase, "Reads/writes structured data", "TLS / PostgreSQL wire")
```

---

## 2. Data-Flow Pipeline Diagram

```mermaid
flowchart TD
    SIM["Simulator\ndata_simulator.py\n50 vehicles x 14 days"] -->|JSON events| RP["Redpanda\nTopic: telemetry\nat-least-once delivery"]

    RP -->|poll batch 500 events| ING["Ingestion Consumer\nPydantic validation\nbatch INSERT ON CONFLICT DO NOTHING\nmanual offset commit after DB write"]

    ING -->|idempotent write| PG[("PostgreSQL\ntelemetry_events\n~50K rows/14d")]
    ING -->|HSET vehicle:vin:status| RD[("Redis\nLive Status Cache\nTTL=24h")]

    PG -->|ordered by ts,seq| SEG["Segmentation Engine\nM4: O(n) state machine\nper-vehicle single pass"]

    SEG --> TRIPS[("trips\nidle_events")]

    TRIPS -->|LEFT JOIN + aggregation| COST["Cost Engine\nM5: daily rollup\nweighted top-K scoring"]

    COST --> CSD[("cost_summary_daily\nmonthly_fleet_cost\nmaterialized view")]

    CSD --> API["FastAPI\nJWT auth, rate limiting\n/fleet/summary, /fleet/offenders\n/vehicles/{id}/cost-summary"]
    RD --> API

    API --> DASH["React Dashboard\nFleet overview\nOffender leaderboard\nVehicle drill-down\nLive status card"]
    API --> AI["AI Assistant\nSQL-grounded context + user prompt\nLLM-generated response\nAudit log to agent_logs"]

    DASH --> FM["Fleet Manager"]
    AI --> FM
```

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

## 5. Deployment Topology

```mermaid
flowchart LR
    subgraph "docker compose (local) / K8s (prod)"
        direction TB
        RP_C["redpanda\nkafka:9092"]
        PG_C["postgres\ntimescaledb:pg16\n:5432"]
        RD_C["redis:7-alpine\n:6379"]
        ING_C["ingestion\nconsumer.py\nbatch=500"]
        SEG_C["seeder\nseed_and_run.py\none-shot on startup"]
        API_C["api\nfastapi+uvicorn\n:8000"]
        DASH_C["dashboard\nnginx:alpine\n:80\n/api -> api:8000"]
    end

    subgraph "External"
        GROQ_E["Groq API\nopenai/gpt-oss-20b"]
        SIM_E["Simulator\ndata_simulator.py"]
    end

    SIM_E -->|kafka produce| RP_C
    RP_C --> ING_C
    ING_C --> PG_C
    ING_C --> RD_C
    SEG_C --> PG_C
    PG_C --> API_C
    RD_C --> API_C
    API_C --> GROQ_E
    DASH_C --> API_C
    BROWSER["Browser\nhttp://localhost:80"] --> DASH_C
```

---

## 6. Failure Sequence — Consumer Crash & Recovery

```mermaid
sequenceDiagram
    participant RP as Redpanda
    participant CON as Ingestion Consumer
    participant PG as PostgreSQL
    participant RD as Redis

    Note over CON: Normal operation
    RP->>CON: poll batch (500 msgs)
    CON->>PG: INSERT batch (ON CONFLICT DO NOTHING)
    PG-->>CON: OK
    CON->>RD: HSET pipeline (live status)
    RD-->>CON: OK
    CON->>RP: commit offsets
    Note over CON: Batch committed

    Note over CON: Failure scenario
    RP->>CON: poll batch (500 msgs)
    CON->>PG: INSERT batch
    PG--xCON: Connection error
    CON->>PG: ROLLBACK
    CON->>CON: sleep 2s, reconnect
    Note over RP: Offsets NOT committed
    CON->>RP: re-poll same batch
    CON->>PG: INSERT batch (ON CONFLICT DO NOTHING)
    Note over PG: Duplicates silently dropped\nby unique index (vin, ts, seq)
    PG-->>CON: OK
    CON->>RP: commit offsets
    Note over CON: At-least-once delivery\n+ idempotent writes = exactly-once semantics
```

---

## 7. AI Assistant Context-Grounded Response Flow

```mermaid
sequenceDiagram
    participant U as User (Dashboard)
    participant API as FastAPI /chat
    participant DB as PostgreSQL
    participant LLM as Groq LLM
    participant LOG as audit_log

    U->>API: POST /chat {query, from_date, to_date}
    API->>API: verify JWT, extract fleet_id
    API->>LOG: audit_log(user, "ai_query", "chat")
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

    API->>DB: INSERT INTO agent_logs
    API-->>U: {answer, tool_calls: []}
```
