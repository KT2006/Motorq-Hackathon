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
    """Lightweight re-implementation so seeder has no import dependency on segment.py."""
    log.info("running segmentation for all vehicles...")
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT vin FROM telemetry_events")
        vins = [r[0] for r in cur.fetchall()]

    log.info("segmenting %d VINs", len(vins))
    for vin in vins:
        _segment_vin(conn, vin.strip())
    conn.commit()
    log.info("segmentation_done vins=%d", len(vins))

def _segment_vin(conn, vin: str):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Clear old results (idempotent re-run)
        cur.execute("DELETE FROM idle_events WHERE vin = %s", (vin,))
        cur.execute("DELETE FROM trips WHERE vin = %s", (vin,))
        cur.execute("""
            SELECT ts, lat, lon, speed_kmh, odo_km, ignition_status, evt, seq
            FROM telemetry_events WHERE vin = %s
            ORDER BY ts ASC, seq ASC
        """, (vin,))
        rows = cur.fetchall()

    if not rows:
        return

    SPEED_THRESH = 3.0
    MIN_IDLE_SEC = 60
    MAX_INTIP_IDLE_SEC = 900

    state = "NOT_IN_TRIP"
    trip = None
    idle = None
    trips_out = []
    idles_out = []
    speed_samples = []

    for r in rows:
        ts = r["ts"]
        lat, lon = r["lat"], r["lon"]
        speed = float(r["speed_kmh"])
        odo = float(r["odo_km"])
        ign = r["ignition_status"]
        evt = r["evt"]

        if state == "NOT_IN_TRIP":
            if evt == "TRIP_START" or (speed > SPEED_THRESH and ign):
                trip = {"vin": vin, "start_ts": ts, "start_lat": lat, "start_lon": lon,
                        "start_odo": odo, "fuel_start": None}
                speed_samples = [speed]
                state = "DRIVING"
        elif state == "DRIVING":
            speed_samples.append(speed)
            if evt == "TRIP_END" or not ign:
                _close_trip(trip, ts, lat, lon, odo, speed_samples, trips_out)
                trip = None
                state = "NOT_IN_TRIP"
            elif speed <= SPEED_THRESH and ign:
                idle = {"vin": vin, "trip_id": None, "start_ts": ts, "lat": lat, "lon": lon,
                        "idle_type": "in_trip"}
                state = "IN_TRIP_IDLE"
        elif state == "IN_TRIP_IDLE":
            idle_secs = (ts - idle["start_ts"]).total_seconds() if hasattr(ts, "total_seconds") else \
                        (ts - idle["start_ts"]).total_seconds() if isinstance(ts, datetime) else 0
            try:
                idle_secs = (ts - idle["start_ts"]).total_seconds()
            except Exception:
                idle_secs = 0
            if idle_secs > MAX_INTIP_IDLE_SEC or evt == "TRIP_END" or not ign:
                idles_out.append({**idle, "end_ts": ts,
                                   "duration_min": round(idle_secs / 60, 2),
                                   "fuel_burned_l": None, "energy_burned_kwh": None})
                _close_trip(trip, ts, lat, lon, odo, speed_samples, trips_out)
                trip = None
                idle = None
                state = "NOT_IN_TRIP"
            elif speed > SPEED_THRESH:
                idle_secs2 = (ts - idle["start_ts"]).total_seconds()
                if idle_secs2 >= MIN_IDLE_SEC:
                    idles_out.append({**idle, "end_ts": ts,
                                       "duration_min": round(idle_secs2 / 60, 2),
                                       "fuel_burned_l": None, "energy_burned_kwh": None})
                idle = None
                speed_samples.append(speed)
                state = "DRIVING"

    # Flush results
    with conn.cursor() as cur:
        for t in trips_out:
            cur.execute("""
                INSERT INTO trips
                  (vin, start_ts, end_ts, start_lat, start_lon, end_lat, end_lon,
                   distance_km, duration_min, avg_speed_kmh, idle_duration_min)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (t["vin"], t["start_ts"], t["end_ts"],
                  t["start_lat"], t["start_lon"], t["end_lat"], t["end_lon"],
                  t["distance_km"], t["duration_min"], t["avg_speed_kmh"], 0))
        for ie in idles_out:
            cur.execute("""
                INSERT INTO idle_events
                  (vin, start_ts, end_ts, duration_min, lat, lon, idle_type)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (ie["vin"], ie["start_ts"], ie["end_ts"],
                  ie["duration_min"], ie["lat"], ie["lon"], ie["idle_type"]))

def _close_trip(trip, end_ts, end_lat, end_lon, end_odo, speed_samples, trips_out):
    if trip is None:
        return
    dur_sec = (end_ts - trip["start_ts"]).total_seconds()
    dist = max(0, round(end_odo - trip["start_odo"], 2))
    avg_spd = round(sum(speed_samples) / len(speed_samples), 2) if speed_samples else 0
    trips_out.append({
        "vin": trip["vin"], "start_ts": trip["start_ts"], "end_ts": end_ts,
        "start_lat": trip["start_lat"], "start_lon": trip["start_lon"],
        "end_lat": end_lat, "end_lon": end_lon,
        "distance_km": dist, "duration_min": round(dur_sec / 60, 2),
        "avg_speed_kmh": avg_spd,
    })

def run_cost_rollup(conn):
    """Simple daily cost rollup — writes cost_summary_daily."""
    log.info("running cost rollup...")
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO cost_summary_daily
              (vehicle_id, summary_date, total_distance_km, total_drive_min,
               total_idle_min, available_min, fuel_cost, idle_cost, utilisation_pct)
            SELECT
                v.vehicle_id,
                t.trip_date,
                COALESCE(SUM(t.distance_km), 0),
                COALESCE(SUM(t.duration_min), 0),
                COALESCE(SUM(ie.idle_min), 0),
                1440,
                COALESCE(SUM(t.distance_km) * 0.09 * 100, 0),  -- ₹100/L petrol approx
                COALESCE(SUM(ie.idle_min) / 60.0 * 0.6 * 92, 0),  -- diesel idle approx
                LEAST(100, COALESCE(SUM(t.duration_min) / 1440.0 * 100, 0))
            FROM vehicles v
            LEFT JOIN (
                SELECT vin, date(start_ts) AS trip_date,
                       SUM(distance_km) AS distance_km, SUM(duration_min) AS duration_min
                FROM trips
                GROUP BY vin, date(start_ts)
            ) t ON t.vin = v.vin
            LEFT JOIN (
                SELECT vin, date(start_ts) AS idle_date, SUM(duration_min) AS idle_min
                FROM idle_events
                GROUP BY vin, date(start_ts)
            ) ie ON ie.vin = v.vin AND ie.idle_date = t.trip_date
            WHERE t.trip_date IS NOT NULL
            GROUP BY v.vehicle_id, t.trip_date
            ON CONFLICT (vehicle_id, summary_date) DO UPDATE
                SET total_distance_km = EXCLUDED.total_distance_km,
                    total_drive_min   = EXCLUDED.total_drive_min,
                    total_idle_min    = EXCLUDED.total_idle_min,
                    fuel_cost         = EXCLUDED.fuel_cost,
                    idle_cost         = EXCLUDED.idle_cost,
                    utilisation_pct   = EXCLUDED.utilisation_pct
        """)
        conn.commit()
    log.info("cost_rollup_done")
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
