"""
Fuel, Idling & Utilisation Cost — Synthetic Data Simulator
============================================================
Generates realistic connected-vehicle telemetry for a mixed ICE/EV fleet:
trip + idle state machine, fuel/energy burn, GPS noise, duplicate and
out-of-order events (per the hackathon brief's ingestion requirements).

Two output modes:
  --mode bulk    -> vectorized historical seed dataset written to Parquet
                     (fast batch generation, feeds your batch-analytics /
                     trip-segmentation / cost-summary pipeline)
  --mode stream  -> near-real-time event producer to Kafka
                     (feeds your live ingestion path + dashboard demo)

Dependencies:  pip install pandas numpy faker kafka-python

Usage:
  python data_simulator.py --mode bulk --vehicles 100000 --days 30 --out ./seed_data
  python data_simulator.py --mode stream --vehicles 5000 --rate 2000 --topic telemetry

Scaling note:
  This is a single-process reference implementation, clear enough to read
  and to justify in your Solution Document. To actually reach 100,000
  vehicles x 30 days in reasonable time, shard the vehicle list across a
  multiprocessing.Pool (one worker per CPU core, each calling
  simulate_vehicle_day for its slice) and write one Parquet file per
  worker/batch — the per-vehicle simulation is embarrassingly parallel.
"""

import argparse
import json
import math
import os
import random
import string
import time
import uuid
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

# ----------------------------------------------------------------------------
# Config — tune these per your demo story
# ----------------------------------------------------------------------------

VIN_CHARS = "".join(c for c in string.ascii_uppercase + string.digits if c not in "IOQ")
FUEL_TYPES = ["petrol", "diesel", "hybrid", "ev"]
FUEL_TYPE_WEIGHTS = [0.45, 0.25, 0.10, 0.20]
VEHICLE_MAKES = ["Volvo", "Subaru", "Toyota", "Mahindra", "Tata", "Hyundai", "Ford", "Nissan"]

# Bounding box used to place trips (default: adjust to whichever city you're demoing)
CITY_LAT_RANGE = (12.90, 13.20)
CITY_LON_RANGE = (80.10, 80.30)

# Assumption constants — cite real sources for these in your Solution Doc, Section 2.2
IDLE_BURN_RATE = {          # L/hour for ICE, kWh/hour for EV (climate-control draw)
    "petrol": 0.6, "diesel": 0.5, "hybrid": 0.3, "ev": 0.9,
}
CONSUMPTION_PER_KM = {       # L/km for ICE, kWh/km for EV, roughly at cruising speed
    "petrol": 0.09, "diesel": 0.07, "hybrid": 0.05, "ev": 0.18,
}

# ----------------------------------------------------------------------------
# Master data generation (fleets, vehicles, drivers)
# ----------------------------------------------------------------------------

def gen_vin() -> str:
    """17-char VIN, excluding I/O/Q. This is a plausible-looking synthetic key,
    not a real ISO 3779 check-digit VIN — swap in the real checksum algorithm
    if your 'VIN validation via regex/check digit' deliverable needs real logic."""
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
        "tank_capacity_l": [round(random.uniform(40, 70), 1) if ft != "ev" else None for ft in fuel_types],
        "battery_capacity_kwh": [round(random.uniform(40, 90), 1) if ft == "ev" else None for ft in fuel_types],
        "odometer_km_baseline": np.round(np.random.uniform(500, 120000, size=n_vehicles), 1),
    })


# ----------------------------------------------------------------------------
# Trip / idle behaviour — the core simulation logic
# ----------------------------------------------------------------------------

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def random_point():
    return (random.uniform(*CITY_LAT_RANGE), random.uniform(*CITY_LON_RANGE))


def simulate_vehicle_day(vin: str, fuel_type: str, day: datetime, start_odo: float, start_fuel_pct: float):
    """
    State machine per vehicle per day:
      PARKED (overnight, engine off)
        -> TRIP (2-5 trips/day, with embedded red-light idles + harsh-brake events)
        -> DEPOT/LOADING IDLE (occasional, engine on, stationary)
        -> PARKED
    Returns (events, ending_odo, ending_fuel_pct).
    """
    events = []
    seq = 0
    odo = start_odo
    fuel_pct = start_fuel_pct
    n_trips = random.randint(2, 5)
    t = day.replace(hour=random.randint(6, 9), minute=random.randint(0, 59), second=0, microsecond=0)

    for _ in range(n_trips):
        origin = random_point()
        dest = random_point()
        trip_dist_km = haversine_km(*origin, *dest) * random.uniform(1.1, 1.4)  # road vs. straight-line factor
        avg_speed = random.uniform(18, 45)                # urban traffic, km/h
        duration_min = max(5, (trip_dist_km / avg_speed) * 60)
        n_steps = max(1, int(duration_min * 60 / 8))       # ~1 event every 8 seconds

        events.append(_event(vin, t, *origin, 0, odo, True, fuel_type, fuel_pct, "TRIP_START", seq)); seq += 1

        for i in range(1, n_steps + 1):
            frac = i / n_steps
            lat = origin[0] + (dest[0] - origin[0]) * frac + random.gauss(0, 0.0004)   # GPS noise
            lon = origin[1] + (dest[1] - origin[1]) * frac + random.gauss(0, 0.0004)
            is_red_light = random.random() < 0.08           # ~8% of steps are a red-light idle
            speed = 0.0 if is_red_light else max(5, random.gauss(avg_speed, 8))
            step_km = 0 if is_red_light else (trip_dist_km / n_steps)
            odo += step_km
            fuel_pct -= _consumption_delta(fuel_type, step_km)
            t += timedelta(seconds=8)
            evt = "HARSH_BRAKE" if (not is_red_light and random.random() < 0.01) else None
            events.append(_event(vin, t, lat, lon, speed, odo, True, fuel_type, fuel_pct, evt, seq)); seq += 1

        events.append(_event(vin, t, *dest, 0, odo, True, fuel_type, fuel_pct, "TRIP_END", seq)); seq += 1

        if random.random() < 0.3:   # occasional depot/loading idle between trips
            idle_min = random.uniform(5, 25)
            events.append(_event(vin, t, *dest, 0, odo, True, fuel_type, fuel_pct, "IDLE_START", seq)); seq += 1
            fuel_pct -= _idle_burn_delta(fuel_type, idle_min)
            t += timedelta(minutes=idle_min)
            events.append(_event(vin, t, *dest, 0, odo, True, fuel_type, fuel_pct, "IDLE_END", seq)); seq += 1

        t += timedelta(minutes=random.uniform(10, 90))     # gap before the next trip

    return events, odo, max(fuel_pct, 5.0)


def _consumption_delta(fuel_type: str, km: float) -> float:
    """Rough % of tank/battery burned for this distance step. Tune the divisor
    against each vehicle's actual tank_capacity_l / battery_capacity_kwh for realism."""
    base = CONSUMPTION_PER_KM.get(fuel_type, 0.09) * km
    return base / 0.6 if fuel_type != "ev" else base * 1.3


def _idle_burn_delta(fuel_type: str, minutes: float) -> float:
    return IDLE_BURN_RATE.get(fuel_type, 0.6) * (minutes / 60) * 1.5


def _event(vin, ts, lat, lon, speed, odo, ignition, fuel_type, fuel_pct, evt, seq):
    e = {
        "vin": vin, "ts": ts.isoformat(), "lat": round(lat, 5), "lon": round(lon, 5),
        "speed_kmh": round(speed, 1), "odo_km": round(odo, 1), "ignition_status": ignition,
        "evt": evt, "seq": seq,
    }
    if fuel_type == "ev":
        e["soc_pct"] = round(fuel_pct, 1)
    else:
        e["fuel_level_pct"] = round(fuel_pct, 1)
    return e


def inject_noise(events: list, dup_rate=0.01, drop_rate=0.005, reorder_rate=0.02) -> list:
    """Duplicate, drop and shuffle a few events — satisfies the brief's 'bursty,
    out-of-order, duplicate events' ingestion requirement, and is what your
    idempotent-ingestion / dedup-by-seq logic should be tested against."""
    noisy = []
    for e in events:
        if random.random() < drop_rate:
            continue
        noisy.append(e)
        if random.random() < dup_rate:
            noisy.append(dict(e))            # exact duplicate
    if reorder_rate and len(noisy) > 1:
        n_swaps = int(len(noisy) * reorder_rate)
        for _ in range(n_swaps):
            i = random.randint(0, len(noisy) - 2)
            noisy[i], noisy[i + 1] = noisy[i + 1], noisy[i]
    return noisy


# ----------------------------------------------------------------------------
# Postgres helpers
# ----------------------------------------------------------------------------

def get_pg_engine():
    """Create a SQLAlchemy engine from POSTGRES_URL in .env."""
    if not POSTGRES_URL:
        raise RuntimeError(
            "POSTGRES_URL not set. Add it to your .env file:\n"
            "  POSTGRES_URL=postgresql://user:password@host:5432/dbname"
        )
    from sqlalchemy import create_engine, event
    url = POSTGRES_URL.replace("postgres://", "postgresql://")
    engine = create_engine(url, pool_pre_ping=True)

    # Supabase pooler sometimes sets default_transaction_read_only=on — force it off
    @event.listens_for(engine, "connect")
    def set_read_write(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("SET default_transaction_read_only = off")
        cursor.close()
        dbapi_conn.commit()

    return engine


def _upsert_fleets(engine, fleets: pd.DataFrame):
    """Insert fleets, skipping conflicts on fleet_id."""
    rows = fleets.to_dict(orient="records")
    import psycopg2
    from sqlalchemy import text
    with engine.begin() as conn:
        for r in rows:
            conn.execute(text("""
                INSERT INTO fleets (fleet_id, fleet_name, operator_name, fleet_type, region)
                VALUES (:fleet_id, :fleet_name, :operator_name, :fleet_type, :region)
                ON CONFLICT (fleet_id) DO NOTHING
            """), r)
    print(f"  fleets: {len(rows)} rows inserted/skipped")


def _upsert_vehicles(engine, vehicles: pd.DataFrame):
    """Insert vehicles, skipping conflicts on vehicle_id."""
    rows = vehicles.to_dict(orient="records")
    from sqlalchemy import text
    with engine.begin() as conn:
        for r in rows:
            conn.execute(text("""
                INSERT INTO vehicles
                    (vehicle_id, vin, fleet_id, make, model, model_year,
                     fuel_type, tank_capacity_l, battery_capacity_kwh, odometer_km_baseline)
                VALUES
                    (:vehicle_id, :vin, :fleet_id, :make, :model, :model_year,
                     :fuel_type, :tank_capacity_l, :battery_capacity_kwh, :odometer_km_baseline)
                ON CONFLICT (vehicle_id) DO NOTHING
            """), r)
    print(f"  vehicles: {len(rows)} rows inserted/skipped")


def _insert_telemetry_batch(engine, events: list):
    """Bulk-insert telemetry events using fast execute_values, ignoring duplicates."""
    if not events:
        return
    import math
    import psycopg2.extras

    df = pd.DataFrame(events)
    df["ts"] = pd.to_datetime(df["ts"], format="ISO8601", utc=True)
    if "fuel_level_pct" not in df.columns:
        df["fuel_level_pct"] = None
    if "soc_pct" not in df.columns:
        df["soc_pct"] = None

    def _clean(v):
        if v is None:
            return None
        if isinstance(v, float) and math.isnan(v):
            return None
        return v

    def _clamp_pct(v):
        """Clamp to 0-100, converting NaN to None."""
        if v is None:
            return None
        if isinstance(v, float) and math.isnan(v):
            return None
        return max(0.0, min(100.0, float(v)))

    rows = [
        (
            r.vin, r.ts,
            r.lat, r.lon,
            r.speed_kmh, r.odo_km,
            bool(r.ignition_status),
            _clamp_pct(r.fuel_level_pct),
            _clamp_pct(r.soc_pct),
            _clean(r.evt),
            int(r.seq),
        )
        for r in df.itertuples(index=False)
    ]

    sql = """
        INSERT INTO telemetry_events
            (vin, ts, lat, lon, speed_kmh, odo_km, ignition_status,
             fuel_level_pct, soc_pct, evt, seq)
        VALUES %s
        ON CONFLICT (vin, ts, seq) DO NOTHING
    """
    for attempt in range(3):
        raw = engine.raw_connection()
        try:
            with raw.cursor() as cur:
                psycopg2.extras.execute_values(cur, sql, rows, page_size=2000)
            raw.commit()
            return
        except Exception as e:
            raw.rollback()
            if "read-only" in str(e).lower() and attempt < 2:
                print(f"  read-only connection, retrying ({attempt+1}/3)...")
                time.sleep(2)
                continue
            raise
        finally:
            raw.close()


# ----------------------------------------------------------------------------
# Bulk mode — writes master data + telemetry directly to Postgres
# ----------------------------------------------------------------------------

def run_bulk(n_vehicles: int, n_days: int, out_dir: str, flush_every_events: int = 50_000):
    engine = get_pg_engine()
    print(f"Connected to Postgres: {engine.url.host}")

    fleets = gen_fleets(max(1, n_vehicles // 200))
    vehicles = gen_vehicles(n_vehicles, fleets)

    print("Inserting fleets and vehicles...")
    _upsert_fleets(engine, fleets)
    _upsert_vehicles(engine, vehicles)

    start_day = datetime.now(timezone.utc) - timedelta(days=n_days)
    batch_events = []
    total_events = 0

    for _, v in vehicles.iterrows():
        odo, fuel_pct = v["odometer_km_baseline"], random.uniform(40, 95)
        for d in range(n_days):
            day = start_day + timedelta(days=d)
            day_events, odo, fuel_pct = simulate_vehicle_day(v["vin"], v["fuel_type"], day, odo, fuel_pct)
            batch_events.extend(inject_noise(day_events))

        if len(batch_events) >= flush_every_events:
            _insert_telemetry_batch(engine, batch_events)
            total_events += len(batch_events)
            print(f"  flushed {total_events:,} events so far...")
            batch_events = []

    if batch_events:
        _insert_telemetry_batch(engine, batch_events)
        total_events += len(batch_events)

    print(f"\nDone: {n_vehicles} vehicles x {n_days} days -> {total_events:,} telemetry events written to Postgres")
    print("For true 100K-vehicle scale, shard `vehicles` across a multiprocessing.Pool "
          "(one worker per CPU core) rather than running this loop single-threaded.")


# ----------------------------------------------------------------------------
# Stream mode — near-real-time producer to Kafka (for the live ingestion demo)
# ----------------------------------------------------------------------------

def run_stream(n_vehicles: int, target_rate: int, topic: str, bootstrap: str = "localhost:9092"):
    from kafka import KafkaProducer     # pip install kafka-python

    producer = KafkaProducer(bootstrap_servers=bootstrap,
                              value_serializer=lambda v: json.dumps(v).encode("utf-8"))

    fleets = gen_fleets(max(1, n_vehicles // 200))
    vehicles = gen_vehicles(n_vehicles, fleets)
    state = {
        v["vin"]: {"odo": v["odometer_km_baseline"], "fuel": random.uniform(40, 95), "fuel_type": v["fuel_type"]}
        for _, v in vehicles.iterrows()
    }

    print(f"Streaming ~{target_rate} events/sec across {n_vehicles} vehicles to topic '{topic}'")
    try:
        while True:
            batch_vins = random.sample(list(state.keys()), min(target_rate, len(state)))
            for vin in batch_vins:
                s = state[vin]
                day_events, s["odo"], s["fuel"] = simulate_vehicle_day(
                    vin, s["fuel_type"], datetime.now(timezone.utc), s["odo"], s["fuel"])
                for e in inject_noise(day_events[:3]):     # push a small slice per tick to approximate real-time
                    producer.send(topic, e)
            producer.flush()
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("Stopped.")


# ----------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["bulk", "stream"], required=True)
    p.add_argument("--vehicles", type=int, default=1000)
    p.add_argument("--days", type=int, default=7, help="bulk mode only")
    p.add_argument("--out", type=str, default="./seed_data", help="bulk mode only")
    p.add_argument("--rate", type=int, default=500, help="stream mode: target events/sec")
    p.add_argument("--topic", type=str, default="telemetry", help="stream mode only")
    p.add_argument("--bootstrap", type=str, default="localhost:9092", help="stream mode only")
    args = p.parse_args()

    if args.mode == "bulk":
        run_bulk(args.vehicles, args.days, args.out)
    else:
        run_stream(args.vehicles, args.rate, args.topic, args.bootstrap)


if __name__ == "__main__":
    main()