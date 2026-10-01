"""
Fuel, Idling & Utilisation Cost — Synthetic Data Simulator
============================================================
Generates realistic connected-vehicle telemetry for a mixed ICE/EV fleet:
trip + idle state machine, fuel/energy burn, GPS noise, duplicate and
out-of-order events (per the hackathon brief's ingestion requirements).

Two output modes:
  --mode bulk    -> multiprocessed historical seed dataset written directly
                     to Postgres (embarrassingly parallel — one worker per
                     CPU core, each simulates its vehicle slice)
  --mode stream  -> near-real-time event producer to Kafka
                     (feeds your live ingestion path + dashboard demo)

Dependencies:  pip install pandas numpy faker kafka-python psycopg2-binary

Usage:
  # 100K vehicles x 1 day — uses up to 8 workers automatically
  python data_simulator.py --mode bulk --vehicles 100000 --days 1

  # Demo scale (fast)
  python data_simulator.py --mode bulk --vehicles 50 --days 14

  # Live stream
  python data_simulator.py --mode stream --vehicles 5000 --rate 2000 --topic telemetry

Scaling note:
  Each worker connects independently to Postgres and flushes its vehicle
  slice in batches of 50K events. At the current one-minute trip cadence,
  100K vehicles x 1 day generates roughly 14M events; runtime and storage
  depend on the host.
"""

import argparse
import json
import math
import os
import random
import string
import time
import uuid
import multiprocessing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

# Load .env from the project root (one level up from simulator/)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)

POSTGRES_URL = os.getenv("POSTGRES_URL")

try:
    from faker import Faker
    fake = Faker()
except ImportError:
    fake = None

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VIN_CHARS = "".join(c for c in string.ascii_uppercase + string.digits if c not in "IOQ")
FUEL_TYPES = ["petrol", "diesel", "hybrid", "ev"]
FUEL_TYPE_WEIGHTS = [0.45, 0.25, 0.10, 0.20]
VEHICLE_MAKES = ["Volvo", "Subaru", "Toyota", "Mahindra", "Tata", "Hyundai", "Ford", "Nissan"]

CITY_LAT_RANGE = (12.90, 13.20)
CITY_LON_RANGE = (80.10, 80.30)
SAMPLE_INTERVAL_SECONDS = 60

IDLE_BURN_RATE = {
    "petrol": 0.6, "diesel": 0.5, "hybrid": 0.3, "ev": 0.9,
}
CONSUMPTION_PER_KM = {
    "petrol": 1 / 12.0,
    "diesel": 1 / 15.0,
    "hybrid": 1 / 18.0,
    "ev": 1 / 5.5,
}

# ---------------------------------------------------------------------------
# Master data generation
# ---------------------------------------------------------------------------

def gen_vin() -> str:
    return "".join(random.choice(VIN_CHARS) for _ in range(17))


def gen_fleets(n_fleets: int) -> pd.DataFrame:
    types = ["commercial", "rental", "lender", "dealership"]
    return pd.DataFrame({
        "fleet_id": [str(uuid.uuid4()) for _ in range(n_fleets)],
        "fleet_name": [f"{(fake.company() if fake else 'Fleet')} {i}" for i in range(n_fleets)],
        "operator_name": [f"{(fake.name() if fake else 'Operator')} {i}" for i in range(n_fleets)],
        "fleet_type": [random.choice(types) for _ in range(n_fleets)],
        "region": ["Chennai" for _ in range(n_fleets)],
    })


VEHICLE_MODELS = {
    "Volvo": ["FH16", "FM", "FMX"],
    "Subaru": ["Forester", "Outback", "Impreza"],
    "Toyota": ["Innova", "Fortuner", "Hilux"],
    "Mahindra": ["Scorpio", "XUV500", "Bolero"],
    "Tata": ["Nexon", "Harrier", "Safari"],
    "Hyundai": ["Creta", "Tucson", "Venue"],
    "Ford": ["Endeavour", "EcoSport", "Figo"],
    "Nissan": ["Magnite", "Kicks", "Terrano"],
}


def gen_vehicles(n_vehicles: int, fleets: pd.DataFrame) -> pd.DataFrame:
    fuel_types = np.random.choice(FUEL_TYPES, size=n_vehicles, p=FUEL_TYPE_WEIGHTS)
    fleet_ids = np.random.choice(fleets["fleet_id"], size=n_vehicles)
    makes = np.random.choice(VEHICLE_MAKES, size=n_vehicles)
    models = [random.choice(VEHICLE_MODELS[m]) for m in makes]
    model_years = np.random.randint(2015, 2025, size=n_vehicles)
    return pd.DataFrame({
        "vehicle_id": [str(uuid.uuid4()) for _ in range(n_vehicles)],
        "vin": [gen_vin() for _ in range(n_vehicles)],
        "fleet_id": fleet_ids,
        "make": makes,
        "model": models,
        "model_year": model_years.tolist(),
        "fuel_type": fuel_types,
        "tank_capacity_l": [
            round(random.uniform(40, 70), 1) if ft != "ev" else None
            for ft in fuel_types
        ],
        "battery_capacity_kwh": [
            round(random.uniform(40, 90), 1) if ft == "ev" else None
            for ft in fuel_types
        ],
        "odometer_km_baseline": np.round(
            np.random.uniform(500, 120000, size=n_vehicles), 1
        ),
    })


# ---------------------------------------------------------------------------
# Trip / idle simulation — the core state machine
# ---------------------------------------------------------------------------

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def random_point():
    return (random.uniform(*CITY_LAT_RANGE), random.uniform(*CITY_LON_RANGE))


def simulate_vehicle_day(
    vin: str,
    fuel_type: str,
    day: datetime,
    start_odo: float,
    start_fuel_pct: float,
    tank_capacity_l: float = 50.0,
    battery_capacity_kwh: float = 60.0,
):
    """
    State machine per vehicle per day:
      PARKED (overnight) -> TRIP (2-5/day, with embedded red-light idles
      + HARSH_BRAKE events) -> DEPOT IDLE -> PARKED
    Returns (events, ending_odo, ending_fuel_pct).
    """
    events = []
    seq = 0
    odo = start_odo
    fuel_pct = start_fuel_pct
    n_trips = random.randint(2, 5)
    t = day.replace(
        hour=random.randint(6, 9),
        minute=random.randint(0, 59),
        second=0,
        microsecond=0,
    )

    for _ in range(n_trips):
        origin = random_point()
        dest = random_point()
        trip_dist_km = haversine_km(*origin, *dest) * random.uniform(1.1, 1.4)
        avg_speed = random.uniform(18, 45)
        duration_seconds = max(300, trip_dist_km / avg_speed * 3600)
        n_steps = max(1, round(duration_seconds / SAMPLE_INTERVAL_SECONDS))
        sample_seconds = duration_seconds / n_steps

        events.append(
            _event(vin, t, *origin, 0, odo, True, fuel_type, fuel_pct, "TRIP_START", seq)
        )
        seq += 1

        raw_speeds = [
            0.0 if random.random() < 0.08 else max(5.0, random.gauss(avg_speed, 8))
            for _ in range(n_steps)
        ]
        if not any(raw_speeds):
            raw_speeds[0] = avg_speed
        moving_distance = sum(raw_speeds) * sample_seconds / 3600
        speed_scale = trip_dist_km / moving_distance
        speeds = [speed * speed_scale for speed in raw_speeds]
        travelled_km = 0.0

        for i in range(1, n_steps + 1):
            speed = speeds[i - 1]
            step_km = speed * sample_seconds / 3600
            travelled_km += step_km
            frac = travelled_km / trip_dist_km
            lat = origin[0] + (dest[0] - origin[0]) * frac + random.gauss(0, 0.0004)
            lon = origin[1] + (dest[1] - origin[1]) * frac + random.gauss(0, 0.0004)
            odo += step_km
            fuel_pct -= _consumption_delta(
                fuel_type, step_km, tank_capacity_l, battery_capacity_kwh
            )
            t += timedelta(seconds=sample_seconds)
            evt = "HARSH_BRAKE" if speed > 0 and random.random() < 0.01 else None
            events.append(
                _event(vin, t, lat, lon, speed, odo, True, fuel_type, fuel_pct, evt, seq)
            )
            seq += 1

        events.append(
            _event(vin, t, *dest, 0, odo, True, fuel_type, fuel_pct, "TRIP_END", seq)
        )
        seq += 1

        if random.random() < 0.3:
            idle_min = random.uniform(5, 25)
            events.append(
                _event(vin, t, *dest, 0, odo, True, fuel_type, fuel_pct, "IDLE_START", seq)
            )
            seq += 1
            fuel_pct -= _idle_burn_delta(
                fuel_type, idle_min, tank_capacity_l, battery_capacity_kwh
            )
            t += timedelta(minutes=idle_min)
            events.append(
                _event(vin, t, *dest, 0, odo, True, fuel_type, fuel_pct, "IDLE_END", seq)
            )
            seq += 1

        t += timedelta(minutes=random.uniform(10, 90))

    return events, odo, max(fuel_pct, 5.0)


def _consumption_delta(
    fuel_type: str,
    km: float,
    tank_capacity_l: float = 50.0,
    battery_capacity_kwh: float = 60.0,
) -> float:
    capacity = battery_capacity_kwh if fuel_type == "ev" else tank_capacity_l
    return CONSUMPTION_PER_KM[fuel_type] * km / capacity * 100


def _idle_burn_delta(
    fuel_type: str,
    minutes: float,
    tank_capacity_l: float = 50.0,
    battery_capacity_kwh: float = 60.0,
) -> float:
    capacity = battery_capacity_kwh if fuel_type == "ev" else tank_capacity_l
    return IDLE_BURN_RATE[fuel_type] * (minutes / 60) / capacity * 100


def _event(vin, ts, lat, lon, speed, odo, ignition, fuel_type, fuel_pct, evt, seq):
    e = {
        "vin": vin,
        "ts": ts.isoformat(),
        "lat": round(lat, 5),
        "lon": round(lon, 5),
        "speed_kmh": round(speed, 1),
        "odo_km": round(odo, 1),
        "ignition_status": ignition,
        "evt": evt,
        "seq": seq,
    }
    if fuel_type == "ev":
        e["soc_pct"] = round(max(5.0, min(100.0, fuel_pct)), 1)
        e["fuel_level_pct"] = None
    else:
        e["fuel_level_pct"] = round(max(5.0, min(100.0, fuel_pct)), 1)
        e["soc_pct"] = None
    return e


def inject_noise(events: list, dup_rate=0.01, drop_rate=0.005, reorder_rate=0.02) -> list:
    """
    Inject duplicates, drops and out-of-order events.
    This satisfies the brief's ingestion requirement for bursty, out-of-order,
    duplicate events — and exercises your idempotent dedup logic.
    """
    noisy = []
    for e in events:
        if random.random() < drop_rate:
            continue
        noisy.append(e)
        if random.random() < dup_rate:
            noisy.append(dict(e))  # exact duplicate
    if reorder_rate and len(noisy) > 1:
        n_swaps = int(len(noisy) * reorder_rate)
        for _ in range(n_swaps):
            i = random.randint(0, len(noisy) - 2)
            noisy[i], noisy[i + 1] = noisy[i + 1], noisy[i]
    return noisy


# ---------------------------------------------------------------------------
# Postgres helpers
# ---------------------------------------------------------------------------

def get_pg_engine():
    if not POSTGRES_URL:
        raise RuntimeError(
            "POSTGRES_URL not set. Add it to your .env file:\n"
            "  POSTGRES_URL=postgresql://user:password@host:5432/dbname"
        )
    from sqlalchemy import create_engine, event as sa_event
    # Explicitly use psycopg2 driver to avoid SQLAlchemy 2.x defaulting to psycopg3
    url = POSTGRES_URL.replace("postgres://", "postgresql+psycopg2://").replace(
        "postgresql://", "postgresql+psycopg2://"
    )
    engine = create_engine(url, pool_pre_ping=True)

    @sa_event.listens_for(engine, "connect")
    def set_read_write(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("SET default_transaction_read_only = off")
        cursor.close()
        dbapi_conn.commit()

    return engine


def _upsert_fleets(engine, fleets: pd.DataFrame):
    from sqlalchemy import text
    rows = fleets.to_dict(orient="records")
    with engine.begin() as conn:
        for r in rows:
            conn.execute(text("""
                INSERT INTO fleets (fleet_id, fleet_name, operator_name, fleet_type, region)
                VALUES (:fleet_id, :fleet_name, :operator_name, :fleet_type, :region)
                ON CONFLICT (fleet_id) DO NOTHING
            """), r)
    print(f"  fleets: {len(rows)} rows upserted")


def _upsert_vehicles(engine, vehicles: pd.DataFrame):
    """Bulk-insert vehicles using execute_values for speed at 100K scale."""
    import psycopg2.extras

    rows = [
        (
            str(r.vehicle_id), str(r.vin), str(r.fleet_id),
            str(r.make), str(r.model), int(r.model_year),
            str(r.fuel_type),
            float(r.tank_capacity_l) if r.tank_capacity_l is not None else None,
            float(r.battery_capacity_kwh) if r.battery_capacity_kwh is not None else None,
            float(r.odometer_km_baseline),
        )
        for r in vehicles.itertuples(index=False)
    ]

    sql = """
        INSERT INTO vehicles
            (vehicle_id, vin, fleet_id, make, model, model_year,
             fuel_type, tank_capacity_l, battery_capacity_kwh, odometer_km_baseline)
        VALUES %s
        ON CONFLICT (vehicle_id) DO NOTHING
    """
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            psycopg2.extras.execute_values(cur, sql, rows, page_size=2000)
        raw.commit()
    finally:
        raw.close()
    print(f"  vehicles: {len(rows)} rows upserted")


def _insert_telemetry_batch(pg_url: str, events: list):
    """Insert a batch of events. Accepts a pg_url string so it works in worker processes."""
    if not events:
        return 0
    import psycopg2
    import psycopg2.extras

    rows = []
    for e in events:
        fuel_pct = e.get("fuel_level_pct")
        soc_pct = e.get("soc_pct")

        def _clamp(v):
            if v is None:
                return None
            try:
                f = float(v)
                return max(0.0, min(100.0, f)) if not math.isnan(f) else None
            except (TypeError, ValueError):
                return None

        rows.append((
            e["vin"],
            e["ts"],
            e["lat"],
            e["lon"],
            e["speed_kmh"],
            e["odo_km"],
            bool(e["ignition_status"]),
            _clamp(fuel_pct),
            _clamp(soc_pct),
            e.get("evt"),
            int(e["seq"]),
        ))

    sql = """
        INSERT INTO telemetry_events
            (vin, ts, lat, lon, speed_kmh, odo_km, ignition_status,
             fuel_level_pct, soc_pct, evt, seq)
        VALUES %s
        ON CONFLICT (vin, ts, seq) DO NOTHING
        RETURNING 1
    """
    url = pg_url.replace("postgres://", "postgresql://")
    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            inserted_rows = psycopg2.extras.execute_values(
                cur, sql, rows, page_size=2000, fetch=True
            )
        conn.commit()
    finally:
        conn.close()
    return len(inserted_rows)


# ---------------------------------------------------------------------------
# Multiprocessing worker
# ---------------------------------------------------------------------------

def _worker(args):
    """
    Top-level function (must be picklable — no lambdas or closures).
    Simulates a slice of vehicles and writes directly to Postgres.

    args = (worker_id, vehicle_rows, n_days, pg_url, flush_every)
    """
    worker_id, vehicle_rows, n_days, pg_url, flush_every = args

    # Each worker seeds its own random state so results are reproducible
    # per-worker but not correlated across workers.
    random.seed(worker_id * 31337)
    np.random.seed(worker_id * 31337)

    start_day = datetime.now(timezone.utc) - timedelta(days=n_days)
    batch = []
    total = 0

    for v in vehicle_rows:
        vin, fuel_type, odo_baseline = v["vin"], v["fuel_type"], v["odometer_km_baseline"]
        odo = float(odo_baseline)
        fuel_pct = random.uniform(40, 95)

        tank_capacity_l = v.get("tank_capacity_l") or 50.0
        battery_capacity_kwh = v.get("battery_capacity_kwh") or 60.0
        for d in range(n_days):
            day = start_day + timedelta(days=d)
            # Model a refuel/recharge between scheduled daily shifts.
            fuel_pct = random.uniform(75, 95)
            day_events, odo, fuel_pct = simulate_vehicle_day(
                vin, fuel_type, day, odo, fuel_pct,
                tank_capacity_l, battery_capacity_kwh,
            )
            batch.extend(inject_noise(day_events))

        if len(batch) >= flush_every:
            total += _insert_telemetry_batch(pg_url, batch)
            batch = []
            print(f"  [worker-{worker_id}] flushed {total:,} events", flush=True)

    if batch:
        total += _insert_telemetry_batch(pg_url, batch)

    print(f"  [worker-{worker_id}] done — {total:,} events written", flush=True)
    return total


# ---------------------------------------------------------------------------
# Bulk mode — multiprocessed
# ---------------------------------------------------------------------------

def run_bulk(
    n_vehicles: int,
    n_days: int,
    out_dir: str,
    n_workers: int = None,
    flush_every: int = 50_000,
    skip_master: bool = False,
):
    """
    skip_master=True: don't generate/upsert fleets+vehicles — read existing VINs
    from the DB instead. Used when called from seed_and_run.py which already
    seeded master data.
    """
    if n_workers is None:
        n_workers = min(multiprocessing.cpu_count(), 8)

    pg_url = POSTGRES_URL.replace("postgres://", "postgresql+psycopg2://").replace(
        "postgresql://", "postgresql+psycopg2://"
    ).replace("postgresql+psycopg2+psycopg2://", "postgresql+psycopg2://")

    if skip_master:
        # Read existing vehicles from the DB (seeder already inserted them)
        import psycopg2
        conn = psycopg2.connect(pg_url.replace("postgresql+psycopg2://", "postgresql://"))
        with conn.cursor() as cur:
            cur.execute(
                "SELECT vin, fuel_type, odometer_km_baseline, "
                "tank_capacity_l, battery_capacity_kwh "
                "FROM vehicles ORDER BY vin LIMIT %s",
                (n_vehicles,),
            )
            rows = cur.fetchall()
        conn.close()
        vehicle_records = [
            {
                "vin": r[0],
                "fuel_type": r[1],
                "odometer_km_baseline": float(r[2]),
                "tank_capacity_l": float(r[3]) if r[3] is not None else None,
                "battery_capacity_kwh": float(r[4]) if r[4] is not None else None,
            }
            for r in rows
        ]
        print(f"Loaded {len(vehicle_records):,} existing vehicles from DB for telemetry generation.")
    else:
        engine = get_pg_engine()
        print(f"Connected to Postgres: {engine.url.host}")
        print(f"Generating master data for {n_vehicles:,} vehicles ({n_workers} workers)...")

        n_fleets = max(3, n_vehicles // 200)
        fleets = gen_fleets(n_fleets)
        vehicles = gen_vehicles(n_vehicles, fleets)

        _upsert_fleets(engine, fleets)
        _upsert_vehicles(engine, vehicles)
        engine.dispose()

        vehicle_records = vehicles[
            ["vin", "fuel_type", "odometer_km_baseline", "tank_capacity_l", "battery_capacity_kwh"]
        ].to_dict(
            orient="records"
        )

    print(f"\nStarting telemetry generation: {len(vehicle_records):,} vehicles × {n_days} day(s)...")
    print(f"Using {n_workers} CPU cores — this is embarrassingly parallel.\n")

    slices = [vehicle_records[i::n_workers] for i in range(n_workers)]
    worker_args = [
        (i, slices[i], n_days, pg_url.replace("postgresql+psycopg2://", "postgresql://"), flush_every)
        for i in range(n_workers)
    ]

    t0 = time.time()
    with multiprocessing.Pool(processes=n_workers) as pool:
        results = pool.map(_worker, worker_args)

    elapsed = time.time() - t0
    total_events = sum(results)
    events_per_sec = int(total_events / elapsed) if elapsed > 0 else 0

    print(f"\n{'='*60}")
    print(f"  Vehicles   : {n_vehicles:,}")
    print(f"  Days       : {n_days}")
    print(f"  Events     : {total_events:,}")
    print(f"  Workers    : {n_workers}")
    print(f"  Time       : {elapsed:.1f}s")
    print(f"  Throughput : {events_per_sec:,} events/sec (generation + write)")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Stream mode — near-real-time Kafka producer
# ---------------------------------------------------------------------------

def run_stream(
    n_vehicles: int,
    target_rate: int,
    topic: str,
    bootstrap: str = "localhost:9092",
):
    from kafka import KafkaProducer

    producer = KafkaProducer(
        bootstrap_servers=bootstrap,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    fleets = gen_fleets(max(1, n_vehicles // 200))
    vehicles = gen_vehicles(n_vehicles, fleets)
    state = {
        v["vin"]: {
            "odo": v["odometer_km_baseline"],
            "fuel": random.uniform(40, 95),
            "fuel_type": v["fuel_type"],
        }
        for _, v in vehicles.iterrows()
    }

    print(f"Streaming ~{target_rate} events/sec across {n_vehicles} vehicles → topic '{topic}'")
    try:
        while True:
            batch_vins = random.sample(list(state.keys()), min(target_rate, len(state)))
            for vin in batch_vins:
                s = state[vin]
                day_events, s["odo"], s["fuel"] = simulate_vehicle_day(
                    vin, s["fuel_type"], datetime.now(timezone.utc), s["odo"], s["fuel"]
                )
                for e in inject_noise(day_events[:3]):
                    producer.send(topic, e)
            producer.flush()
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("Stopped.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Fleet telemetry simulator")
    p.add_argument("--mode", choices=["bulk", "stream"], required=True)
    p.add_argument("--vehicles", type=int, default=1000,
                   help="Number of vehicles to simulate")
    p.add_argument("--days", type=int, default=1,
                   help="Days of history (bulk mode). 1 day ≈ 140 events/vehicle.")
    p.add_argument("--out", type=str, default="./seed_data",
                   help="Output directory (unused, kept for backwards compat)")
    p.add_argument("--workers", type=int, default=None,
                   help="CPU workers for bulk mode (default: all cores)")
    p.add_argument("--skip-master", action="store_true",
                   help="Skip fleet/vehicle upsert — read existing VINs from DB instead")
    p.add_argument("--rate", type=int, default=500,
                   help="Target events/sec (stream mode)")
    p.add_argument("--topic", type=str, default="telemetry",
                   help="Kafka topic (stream mode)")
    p.add_argument("--bootstrap", type=str, default="localhost:9092",
                   help="Kafka bootstrap servers (stream mode)")
    args = p.parse_args()

    if args.mode == "bulk":
        run_bulk(args.vehicles, args.days, args.out,
                 n_workers=args.workers, skip_master=args.skip_master)
    else:
        run_stream(args.vehicles, args.rate, args.topic, args.bootstrap)


if __name__ == "__main__":
    # Required for multiprocessing on macOS (default 'spawn' start method)
    multiprocessing.set_start_method("spawn", force=True)
    main()
