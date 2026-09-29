"""
seed_and_run.py — One-shot seeder for docker compose up.

Execution order:
  1. Wait for Postgres to be reachable
  2. Generate a small synthetic fleet (50 vehicles, 14 days)
  3. Load master data (fleets, vehicles, drivers) into Postgres
  4. Load telemetry_events (bulk Parquet -> Postgres)
  5. Run M4 segmentation engine
  6. Run M5 cost rollup engine
  7. Refresh monthly_fleet_cost materialized view
  8. Publish a stream of live events to Redpanda (for live-status demo)
  9. Exit cleanly — compose restarts are not expected

All parameters are configurable via env vars to keep the compose file clean.
"""

import json
import os
import sys
import time
import uuid
import random
import string
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from segment import segment_vehicle, fetch_distinct_vins as _fetch_vins
from segment import clear_results_for_vin, insert_trips, insert_idle_events, fetch_telemetry_for_vin
from cost_engine import run_rollup, seed_idle_burn_rates, AVAILABLE_MIN_PER_DAY

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seeder")

POSTGRES_URL = os.environ["POSTGRES_URL"].replace("postgres://", "postgresql://")
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")
TOPIC = os.getenv("TELEMETRY_TOPIC", "telemetry")
N_FLEETS = int(os.getenv("SEED_FLEETS", "3"))
N_VEHICLES = int(os.getenv("SEED_VEHICLES", "50"))
N_DAYS = int(os.getenv("SEED_DAYS", "14"))
STREAM_EVENTS = int(os.getenv("SEED_STREAM_EVENTS", "60"))  # 60 live events after bulk load
SKIP_IF_SEEDED = os.getenv("SKIP_IF_SEEDED", "true").lower() == "true"

# ─── helpers ──────────────────────────────────────────────────────────────────

VIN_CHARS = "".join(c for c in string.ascii_uppercase + string.digits if c not in "IOQ")

def gen_vin():
    return "".join(random.choice(VIN_CHARS) for _ in range(17))

def wait_for_postgres(url: str, retries: int = 30):
    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(url)
            conn.close()
            log.info("postgres_ready attempt=%d", attempt)
            return
        except Exception as err:
            log.warning("postgres_not_ready attempt=%d err=%s", attempt, err)
            time.sleep(3)
    raise RuntimeError("Postgres not reachable after %d attempts" % retries)

def is_already_seeded(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM vehicles")
        count = cur.fetchone()[0]
    return count > 0

# ─── master data ──────────────────────────────────────────────────────────────

FLEET_TYPES = ["commercial", "rental", "lender", "dealership"]
MAKES = ["Tata", "Mahindra", "Toyota", "Hyundai", "Ford"]
MODELS = {"Tata": ["Nexon", "Harrier"], "Mahindra": ["Scorpio", "Bolero"],
          "Toyota": ["Innova", "Fortuner"], "Hyundai": ["Creta", "Venue"],
          "Ford": ["Endeavour", "EcoSport"]}
FUEL_TYPES = ["petrol", "diesel", "hybrid", "ev"]
FUEL_WEIGHTS = [0.45, 0.25, 0.10, 0.20]

def seed_master_data(conn):
    log.info("seeding master data: %d fleets, %d vehicles", N_FLEETS, N_VEHICLES)
    fleets = []
    for i in range(N_FLEETS):
        fid = str(uuid.uuid4())
        fleets.append((fid, f"Fleet {i+1}", f"Operator {i+1}",
                        random.choice(FLEET_TYPES), "Chennai"))

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO fleets (fleet_id, fleet_name, operator_name, fleet_type, region)
            VALUES %s ON CONFLICT DO NOTHING
        """, fleets)

    vehicles = []
    vins = []
    for i in range(N_VEHICLES):
        vid = str(uuid.uuid4())
        vin = gen_vin()
        fleet = fleets[i % N_FLEETS][0]
        make = random.choice(MAKES)
        model = random.choice(MODELS[make])
        fuel = random.choices(FUEL_TYPES, weights=FUEL_WEIGHTS)[0]
        year = random.randint(2016, 2024)
        tank = round(random.uniform(40, 70), 1) if fuel != "ev" else None
        battery = round(random.uniform(40, 80), 1) if fuel == "ev" else None
        odo = round(random.uniform(1000, 80000), 1)
        vehicles.append((vid, vin, fleet, make, model, year, fuel,
                          None, tank, battery, odo))
        vins.append((vin, fleet, fuel))

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO vehicles
              (vehicle_id, vin, fleet_id, make, model, model_year, fuel_type,
               engine_displacement_l, tank_capacity_l, battery_capacity_kwh,
               odometer_km_baseline)
            VALUES %s ON CONFLICT DO NOTHING
        """, vehicles)

    conn.commit()
    log.info("master data seeded: %d vehicles", N_VEHICLES)
    return vehicles, vins

# ─── telemetry events ─────────────────────────────────────────────────────────

IDLE_BURN = {"petrol": 0.6, "diesel": 0.5, "hybrid": 0.3, "ev": 0.0}
CITY_LAT = (12.90, 13.20)
CITY_LON = (80.10, 80.30)

def generate_day_events(vin: str, fuel: str, base_date: datetime, seq_offset: int):
    """Generates one day of telemetry for a single vehicle. Returns list of event dicts."""
    events = []
    ts = base_date.replace(hour=6, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
    lat = random.uniform(*CITY_LAT)
    lon = random.uniform(*CITY_LON)
    odo = round(random.uniform(1000, 80000), 1)
    fuel_pct = random.uniform(30, 100) if fuel != "ev" else None
    soc = random.uniform(30, 100) if fuel == "ev" else None
    seq = seq_offset

    def emit(evt_type=None, speed=0.0, ignition=True):
        nonlocal ts, seq
        events.append({
            "vin": vin, "ts": ts.isoformat(), "seq": seq,
            "lat": round(lat, 6), "lon": round(lon, 6),
            "speed_kmh": round(speed, 1), "odo_km": round(odo, 1),
            "ignition_status": ignition,
            "fuel_level_pct": round(fuel_pct, 1) if fuel_pct is not None else None,
            "soc_pct": round(soc, 1) if soc is not None else None,
            "dtc": None, "evt": evt_type,
        })
        seq += 1
        ts += timedelta(seconds=random.randint(10, 30))

    # 2-3 trips per day
    n_trips = random.randint(2, 3)
    for _ in range(n_trips):
        # Pre-trip idle (depot)
        for _ in range(random.randint(2, 5)):
            emit(speed=0.0)
        emit("TRIP_START", speed=0.0)
        # Driving phase
        for _ in range(random.randint(5, 15)):
            spd = random.uniform(20, 80)
            lat += random.uniform(-0.002, 0.002)
            lon += random.uniform(-0.002, 0.002)
            odo += spd * 20 / 3600
            emit(speed=spd)
        # In-trip idle
        if random.random() < 0.5:
            emit("IDLE_START", speed=0.0)
            for _ in range(random.randint(3, 8)):
                emit(speed=0.0)
            emit("IDLE_END", speed=0.0)
        # Resume driving
        for _ in range(random.randint(3, 8)):
            spd = random.uniform(20, 60)
            lat += random.uniform(-0.001, 0.001)
            lon += random.uniform(-0.001, 0.001)
            odo += spd * 20 / 3600
            emit(speed=spd)
        emit("TRIP_END", speed=0.0)
        ts += timedelta(minutes=random.randint(15, 60))

    return events

def seed_telemetry(conn, vehicles):
    log.info("generating telemetry: %d vehicles x %d days", N_VEHICLES, N_DAYS)
    base_date = datetime.now(timezone.utc) - timedelta(days=N_DAYS)
    total = 0
    batch = []
    BATCH_SIZE = 2000

    for vid, vin, fleet, make, model, year, fuel, *_ in vehicles:
        seq_offset = 0
        for day_offset in range(N_DAYS):
            day = base_date + timedelta(days=day_offset)
            # Inject 1 duplicate per vehicle per day to prove idempotency
            events = generate_day_events(vin, fuel, day, seq_offset)
            if events:
                events.append(events[0].copy())  # duplicate — will be dropped by ON CONFLICT
            seq_offset += len(events) + 1
            for e in events:
                batch.append((
                    e["vin"], e["ts"], e["lat"], e["lon"],
                    e["speed_kmh"], e["odo_km"], e["ignition_status"],
                    e["fuel_level_pct"], e["soc_pct"],
                    e["dtc"], e["evt"], e["seq"],
                ))
            if len(batch) >= BATCH_SIZE:
                _flush_telemetry(conn, batch)
                total += len(batch)
                batch = []

    if batch:
        _flush_telemetry(conn, batch)
        total += len(batch)

    conn.commit()
    log.info("telemetry_seeded total_events=%d (duplicates collapsed by ON CONFLICT)", total)

def _flush_telemetry(conn, rows):
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO telemetry_events
              (vin, ts, lat, lon, speed_kmh, odo_km, ignition_status,
               fuel_level_pct, soc_pct, dtc, evt, seq)
            VALUES %s
            ON CONFLICT (vin, ts, seq) DO NOTHING
        """, rows, page_size=500)

# ─── segmentation + cost ──────────────────────────────────────────────────────

def run_segmentation(conn):
    """Run canonical M4 segmentation engine for all vehicles."""
    log.info("running canonical M4 segmentation for all vehicles...")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT v.vin, v.fuel_type
            FROM vehicles v
            WHERE EXISTS (SELECT 1 FROM telemetry_events te WHERE te.vin = v.vin LIMIT 1)
            ORDER BY v.vin
        """)
        vin_list = cur.fetchall()

    log.info("segmenting %d VINs using canonical segment.py", len(vin_list))
    total_trips, total_idles = 0, 0
    for vin, fuel_type in vin_list:
        vin = vin.strip()
        rows = fetch_telemetry_for_vin(conn, vin)
        if not rows:
            continue
        trips, idles = segment_vehicle(rows, vin, fuel_type)
        clear_results_for_vin(conn, vin)
        insert_trips(conn, trips)
        insert_idle_events(conn, idles)
        total_trips += len(trips)
        total_idles += len(idles)
    conn.commit()
    log.info("segmentation_done vins=%d trips=%d idles=%d", len(vin_list), total_trips, total_idles)

def run_cost_rollup(conn):
    """Run canonical M5 cost rollup engine."""
    log.info("running canonical M5 cost rollup...")
    seed_idle_burn_rates(conn)
    n_rows = run_rollup(conn)
    log.info("cost_rollup_done rows=%d", n_rows)
    # Refresh the materialized view
    with conn.cursor() as cur:
        cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY monthly_fleet_cost")
        conn.commit()
    log.info("monthly_fleet_cost_refreshed")

# ─── live-stream demo events ───────────────────────────────────────────────────

def publish_stream_events(conn):
    """Publish STREAM_EVENTS live telemetry events for one vehicle to Redpanda."""
    try:
        from kafka import KafkaProducer
    except ImportError:
        log.warning("kafka-python not installed; skipping live stream publish")
        return

    # Pick a real VIN from the database
    with conn.cursor() as cur:
        cur.execute("SELECT vin FROM vehicles LIMIT 1")
        row = cur.fetchone()

    if not row:
        log.warning("no vehicles found for stream demo")
        return

    vin = row[0].strip()
    log.info("publishing stream demo events vin=%s count=%d", vin, STREAM_EVENTS)

    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda e: json.dumps(e).encode("utf-8"),
        )
        lat = random.uniform(12.90, 13.20)
        lon = random.uniform(80.10, 80.30)
        odo = 50000.0
        for i in range(STREAM_EVENTS):
            lat += random.uniform(-0.0005, 0.0005)
            lon += random.uniform(-0.0005, 0.0005)
            speed = round(random.uniform(10, 60), 1)
            odo += speed * 5 / 3600
            event = {
                "vin": vin, "ts": datetime.now(timezone.utc).isoformat(),
                "seq": int(time.time() * 1000) + i,
                "lat": round(lat, 6), "lon": round(lon, 6),
                "speed_kmh": speed, "odo_km": round(odo, 2),
                "ignition_status": True, "fuel_level_pct": round(60 - i * 0.1, 1),
                "soc_pct": None, "dtc": None,
                "evt": "TRIP_START" if i == 0 else None,
            }
            producer.send(TOPIC, key=vin.encode(), value=event)
        producer.flush()
        producer.close()
        log.info("stream_demo_published vin=%s", vin)
    except Exception as err:
        log.warning("stream_publish_failed (non-fatal): %s", err)

# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    wait_for_postgres(POSTGRES_URL)
    conn = psycopg2.connect(POSTGRES_URL)
    conn.autocommit = False

    if SKIP_IF_SEEDED and is_already_seeded(conn):
        log.info("database already seeded; skipping (set SKIP_IF_SEEDED=false to force re-seed)")
        # Still publish stream events for live demo even if seeded
        publish_stream_events(conn)
        conn.close()
        return

    vehicles, vins = seed_master_data(conn)
    seed_telemetry(conn, vehicles)
    run_segmentation(conn)
    run_cost_rollup(conn)
    publish_stream_events(conn)
    conn.close()
    log.info("seeder_complete")

if __name__ == "__main__":
    main()
