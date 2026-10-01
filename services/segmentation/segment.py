"""
M4: Trip & Idle Segmentation Engine
=====================================
Core module that reads raw telemetry_events from PostgreSQL and produces
meaningful `trips` and `idle_events` rows.

Algorithm: single-pass O(n) state-machine walk per vehicle.
See docs/algorithms.md for the full write-up.

Usage:
    # Process ALL vehicles (full re-run):
    python segment.py

    # Process a single vehicle (debug / spot-check):
    python segment.py --vin "ABCDE12345678901X"

    # Dry run — print results without writing to DB:
    python segment.py --dry-run

Requires: POSTGRES_URL in ../.env (same one the simulator uses)
"""

import argparse
import math
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from config import (
    SPEED_THRESHOLD_KMH,
    MIN_IDLE_DURATION_SEC,
    MIN_TRIP_DISTANCE_KM,
    MIN_TRIP_DURATION_SEC,
    MAX_IN_TRIP_IDLE_SEC,
    IDLE_BURN_RATE,
    INSERT_BATCH_SIZE,
    DEFAULT_OUT_OF_TRIP_IDLE_TYPE,
)


# ---------------------------------------------------------------------------
# Load environment
# ---------------------------------------------------------------------------
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)

POSTGRES_URL = os.getenv("POSTGRES_URL", "")


# ---------------------------------------------------------------------------
# State machine states
# ---------------------------------------------------------------------------
class State(Enum):
    NOT_IN_TRIP = auto()
    DRIVING = auto()
    IN_TRIP_IDLE = auto()


# ---------------------------------------------------------------------------
# Data containers (plain dicts — lightweight, no extra deps)
# ---------------------------------------------------------------------------

def _new_trip(vin: str, row: dict) -> dict:
    """Open a new trip from a telemetry row."""
    return {
        "trip_id": str(uuid.uuid4()),
        "vin": vin,
        "start_ts": row["ts"],
        "start_lat": row["lat"],
        "start_lon": row["lon"],
        "start_odo": row["odo_km"],
        "end_ts": None,
        "end_lat": None,
        "end_lon": None,
        "end_odo": None,
        "speed_sum": 0.0,
        "speed_count": 0,
        "fuel_start": row.get("fuel_level_pct"),
        "soc_start": row.get("soc_pct"),
        "fuel_end": None,
        "soc_end": None,
        "idle_events": [],           # idle events collected during this trip
        "total_idle_sec": 0.0,
    }


def _new_idle(vin: str, row: dict, idle_type: str, trip_id: Optional[str] = None) -> dict:
    """Open a new idle event from a telemetry row."""
    return {
        "idle_id": str(uuid.uuid4()),
        "vin": vin,
        "trip_id": trip_id,
        "start_ts": row["ts"],
        "lat": row["lat"],
        "lon": row["lon"],
        "end_ts": None,
        "idle_type": idle_type,
        "fuel_start": row.get("fuel_level_pct"),
        "soc_start": row.get("soc_pct"),
        "fuel_end": None,
        "soc_end": None,
    }


# ---------------------------------------------------------------------------
# Core segmentation — the O(n) state-machine walk
# ---------------------------------------------------------------------------

def segment_vehicle(
    rows: list[dict],
    vin: str,
    fuel_type: str,
    tank_capacity_l: float = 50.0,
    battery_capacity_kwh: float = 60.0,
) -> tuple[list[dict], list[dict]]:
    """
    Walk through telemetry rows (already sorted by ts ASC) for one vehicle
    and produce (trips, idle_events).

    State machine:
        NOT_IN_TRIP  →  (TRIP_START event OR speed > threshold)  →  DRIVING
        DRIVING      →  (speed ≈ 0 + ignition on)               →  IN_TRIP_IDLE
        IN_TRIP_IDLE →  (speed > threshold)                      →  DRIVING
        IN_TRIP_IDLE →  (idle too long OR ignition off OR TRIP_END) → NOT_IN_TRIP
        DRIVING      →  (ignition off OR TRIP_END)               →  NOT_IN_TRIP

    Returns: (finished_trips, finished_idles)
    """
    if not rows:
        return [], []

    trips: list[dict] = []
    idles: list[dict] = []
    standalone_idles: list[dict] = []  # depot / unauthorized idles (no trip)

    state = State.NOT_IN_TRIP
    current_trip: Optional[dict] = None
    current_idle: Optional[dict] = None

    # Pre-trip idle tracking: if we see idle BEFORE a trip opens, it may
    # become a "pre_trip" idle if a trip starts soon after.
    pending_pre_trip_idle: Optional[dict] = None

    for row in rows:
        speed = float(row["speed_kmh"])
        ignition = bool(row["ignition_status"])
        evt = row.get("evt")  # may be None
        ts = row["ts"]

        # ------------------------------------------------------------------
        # STATE: NOT_IN_TRIP
        # ------------------------------------------------------------------
        if state == State.NOT_IN_TRIP:
            if evt == "TRIP_START" or (speed > SPEED_THRESHOLD_KMH and ignition):
                # ── Close any pending pre-trip idle
                if pending_pre_trip_idle is not None:
                    pending_pre_trip_idle["end_ts"] = ts
                    dur_sec = (pending_pre_trip_idle["end_ts"] - pending_pre_trip_idle["start_ts"]).total_seconds()
                    if dur_sec >= MIN_IDLE_DURATION_SEC:
                        pending_pre_trip_idle["idle_type"] = "pre_trip"
                        standalone_idles.append(pending_pre_trip_idle)
                    pending_pre_trip_idle = None

                # ── Close any depot idle that was running
                if current_idle is not None:
                    _close_idle(current_idle, row, fuel_type)
                    dur_sec = (current_idle["end_ts"] - current_idle["start_ts"]).total_seconds()
                    if dur_sec >= MIN_IDLE_DURATION_SEC:
                        standalone_idles.append(current_idle)
                    current_idle = None

                # ── Open new trip
                current_trip = _new_trip(vin, row)
                state = State.DRIVING

            elif speed <= SPEED_THRESHOLD_KMH and ignition:
                # Vehicle is stationary with ignition on, outside a trip → depot idle
                if current_idle is None:
                    current_idle = _new_idle(vin, row, DEFAULT_OUT_OF_TRIP_IDLE_TYPE)
                # If idle already open, we just let it continue (don't re-open)

            elif not ignition:
                # Ignition off, no trip — close any open idle
                if current_idle is not None:
                    _close_idle(current_idle, row, fuel_type)
                    dur_sec = (current_idle["end_ts"] - current_idle["start_ts"]).total_seconds()
                    if dur_sec >= MIN_IDLE_DURATION_SEC:
                        standalone_idles.append(current_idle)
                    current_idle = None

        # ------------------------------------------------------------------
        # STATE: DRIVING
        # ------------------------------------------------------------------
        elif state == State.DRIVING:
            assert current_trip is not None

            # Track speed for avg calculation
            current_trip["speed_sum"] += speed
            current_trip["speed_count"] += 1

            if evt == "TRIP_END" or not ignition:
                # ── Close the trip
                _close_trip(current_trip, row, fuel_type, tank_capacity_l, battery_capacity_kwh)
                if _trip_is_valid(current_trip):
                    trips.append(current_trip)
                    # Also collect all its in-trip idles
                    idles.extend(current_trip["idle_events"])
                current_trip = None
                state = State.NOT_IN_TRIP

            elif speed <= SPEED_THRESHOLD_KMH and ignition:
                # Transition to in-trip idle
                current_idle = _new_idle(vin, row, "in_trip", trip_id=current_trip["trip_id"])
                state = State.IN_TRIP_IDLE

        # ------------------------------------------------------------------
        # STATE: IN_TRIP_IDLE
        # ------------------------------------------------------------------
        elif state == State.IN_TRIP_IDLE:
            assert current_trip is not None
            assert current_idle is not None

            idle_elapsed = (ts - current_idle["start_ts"]).total_seconds()

            if evt == "TRIP_END" or not ignition:
                # ── Close idle, then close trip
                _close_idle(current_idle, row, fuel_type)
                if (current_idle["end_ts"] - current_idle["start_ts"]).total_seconds() >= MIN_IDLE_DURATION_SEC:
                    current_trip["idle_events"].append(current_idle)
                    current_trip["total_idle_sec"] += (current_idle["end_ts"] - current_idle["start_ts"]).total_seconds()
                current_idle = None

                _close_trip(current_trip, row, fuel_type, tank_capacity_l, battery_capacity_kwh)
                if _trip_is_valid(current_trip):
                    trips.append(current_trip)
                    idles.extend(current_trip["idle_events"])
                current_trip = None
                state = State.NOT_IN_TRIP

            elif idle_elapsed > MAX_IN_TRIP_IDLE_SEC:
                # Idle too long → this trip is effectively over
                _close_idle(current_idle, row, fuel_type)
                if (current_idle["end_ts"] - current_idle["start_ts"]).total_seconds() >= MIN_IDLE_DURATION_SEC:
                    current_trip["idle_events"].append(current_idle)
                    current_trip["total_idle_sec"] += (current_idle["end_ts"] - current_idle["start_ts"]).total_seconds()
                current_idle = None

                _close_trip(current_trip, row, fuel_type, tank_capacity_l, battery_capacity_kwh)
                if _trip_is_valid(current_trip):
                    trips.append(current_trip)
                    idles.extend(current_trip["idle_events"])
                current_trip = None
                state = State.NOT_IN_TRIP

            elif speed > SPEED_THRESHOLD_KMH:
                # Vehicle started moving again → back to driving
                _close_idle(current_idle, row, fuel_type)
                if (current_idle["end_ts"] - current_idle["start_ts"]).total_seconds() >= MIN_IDLE_DURATION_SEC:
                    current_trip["idle_events"].append(current_idle)
                    current_trip["total_idle_sec"] += (current_idle["end_ts"] - current_idle["start_ts"]).total_seconds()
                current_idle = None
                state = State.DRIVING

    # ------------------------------------------------------------------
    # End of data — close any open trip/idle
    # ------------------------------------------------------------------
    if current_idle is not None and current_trip is not None:
        _close_idle(current_idle, rows[-1], fuel_type)
        if (current_idle["end_ts"] - current_idle["start_ts"]).total_seconds() >= MIN_IDLE_DURATION_SEC:
            current_trip["idle_events"].append(current_idle)
            current_trip["total_idle_sec"] += (current_idle["end_ts"] - current_idle["start_ts"]).total_seconds()
    elif current_idle is not None:
        _close_idle(current_idle, rows[-1], fuel_type)
        dur_sec = (current_idle["end_ts"] - current_idle["start_ts"]).total_seconds()
        if dur_sec >= MIN_IDLE_DURATION_SEC:
            standalone_idles.append(current_idle)

    if current_trip is not None:
        _close_trip(current_trip, rows[-1], fuel_type, tank_capacity_l, battery_capacity_kwh)
        if _trip_is_valid(current_trip):
            trips.append(current_trip)
            idles.extend(current_trip["idle_events"])

    idles.extend(standalone_idles)
    return trips, idles


# ---------------------------------------------------------------------------
# Helpers — close events, compute derived fields
# ---------------------------------------------------------------------------

def _close_trip(
    trip: dict,
    last_row: dict,
    fuel_type: str,
    tank_capacity_l: float = 50.0,
    battery_capacity_kwh: float = 60.0,
):
    """Finalize a trip with end coordinates, distance, duration, etc."""
    trip["end_ts"] = last_row["ts"]
    trip["end_lat"] = last_row["lat"]
    trip["end_lon"] = last_row["lon"]
    trip["end_odo"] = last_row["odo_km"]
    trip["fuel_end"] = last_row.get("fuel_level_pct")
    trip["soc_end"] = last_row.get("soc_pct")

    # Distance from odometer delta
    trip["distance_km"] = max(0.0, float(trip["end_odo"]) - float(trip["start_odo"]))

    # Duration in minutes
    duration_sec = (trip["end_ts"] - trip["start_ts"]).total_seconds()
    trip["duration_min"] = round(duration_sec / 60.0, 2)

    # Average speed
    if trip["speed_count"] > 0:
        trip["avg_speed_kmh"] = round(trip["speed_sum"] / trip["speed_count"], 2)
    else:
        trip["avg_speed_kmh"] = 0.0

    # Convert database NUMERIC capacities (Decimal) before arithmetic.
    if fuel_type == "ev":
        soc_delta = _safe_delta(trip["soc_start"], trip["soc_end"])
        trip["energy_used_kwh"] = round(
            max(0.0, soc_delta / 100.0 * float(battery_capacity_kwh)), 3
        ) if soc_delta else None
        trip["fuel_used_l"] = None
    else:
        fuel_delta = _safe_delta(trip["fuel_start"], trip["fuel_end"])
        trip["fuel_used_l"] = round(
            max(0.0, fuel_delta / 100.0 * float(tank_capacity_l)), 3
        ) if fuel_delta else None
        trip["energy_used_kwh"] = None

    # Idle duration in minutes (summed from child idle events)
    trip["idle_duration_min"] = round(trip["total_idle_sec"] / 60.0, 2)


def _close_idle(idle: dict, last_row: dict, fuel_type: str):
    """Finalize an idle event with end time and fuel/energy burned."""
    idle["end_ts"] = last_row["ts"]
    idle["fuel_end"] = last_row.get("fuel_level_pct")
    idle["soc_end"] = last_row.get("soc_pct")

    duration_sec = (idle["end_ts"] - idle["start_ts"]).total_seconds()
    idle["duration_min"] = round(duration_sec / 60.0, 2)

    # Estimate fuel/energy burned during idle from burn rate × duration
    burn_rate = IDLE_BURN_RATE.get(fuel_type, 0.6)
    hours = duration_sec / 3600.0

    if fuel_type == "ev":
        idle["energy_burned_kwh"] = round(burn_rate * hours, 3)
        idle["fuel_burned_l"] = None
    else:
        idle["fuel_burned_l"] = round(burn_rate * hours, 3)
        idle["energy_burned_kwh"] = None


def _trip_is_valid(trip: dict) -> bool:
    """Filter out phantom micro-trips caused by GPS noise."""
    if trip.get("distance_km", 0) < MIN_TRIP_DISTANCE_KM:
        return False
        
    duration_sec = (trip["end_ts"] - trip["start_ts"]).total_seconds()
    if duration_sec < MIN_TRIP_DURATION_SEC:
        return False
        
    # Reject absurdly slow trips (e.g., 0.5km over 24 hours) as noise or test artifacts
    if duration_sec > 0:
        true_avg_speed_kmh = trip.get("distance_km", 0) / (duration_sec / 3600.0)
        if true_avg_speed_kmh < 1.0:
            return False
            
    return True


def _safe_delta(start_val, end_val) -> Optional[float]:
    """Compute the positive difference between two nullable percentage values."""
    if start_val is None or end_val is None:
        return None
    s, e = float(start_val), float(end_val)
    if math.isnan(s) or math.isnan(e):
        return None
    return s - e  # start > end means fuel was consumed


# ============================================================================
# DATABASE I/O
# ============================================================================

def get_connection():
    """Get a raw psycopg2 connection from POSTGRES_URL.
    Explicitly requests a read-write transaction for database compatibility."""
    if not POSTGRES_URL:
        raise RuntimeError(
            "POSTGRES_URL not set. Add it to your .env file:\n"
            "  POSTGRES_URL=postgresql://user:password@host:5432/dbname"
        )
    url = POSTGRES_URL.replace("postgres://", "postgresql://")
    conn = psycopg2.connect(url)
    conn.set_session(readonly=False, autocommit=False)
    return conn


def fetch_distinct_vins(conn) -> list[tuple[str, str]]:
    """Return all (vin, fuel_type) pairs that have telemetry data.
    Uses the vehicles table (small) with an EXISTS check instead of
    a DISTINCT on the 2M+ row telemetry_events table."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT v.vin, v.fuel_type
            FROM vehicles v
            WHERE EXISTS (
                SELECT 1 FROM telemetry_events te
                WHERE te.vin = v.vin
                LIMIT 1
            )
            ORDER BY v.vin
        """)
        return cur.fetchall()


def fetch_telemetry_for_vin(conn, vin: str) -> list[dict]:
    """Fetch all telemetry rows for a VIN using a server-side named cursor
    for streaming. Avoids buffering all rows in psycopg2 before processing.
    Uses the idx_telemetry_vin_ts index."""
    cursor_name = f"seg_{vin.replace(' ', '_')[:10]}_{id(conn) % 10000}"
    rows = []
    with conn.cursor(name=cursor_name, cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.itersize = 5000  # fetch 5000 rows at a time from server
        cur.execute("""
            SELECT vin, ts, lat, lon, speed_kmh, odo_km,
                   ignition_status, fuel_level_pct, soc_pct, evt, seq
            FROM telemetry_events
            WHERE vin = %s
            ORDER BY ts ASC, seq ASC
        """, (vin,))
        for row in cur:
            rows.append(row)
    return rows


def clear_results_for_vin(conn, vin: str):
    """Idempotency: delete existing trips & idle_events for this VIN
    before re-inserting. Order matters — idle_events FK references trips."""
    with conn.cursor() as cur:
        # Delete idle events first (FK to trips)
        cur.execute("DELETE FROM idle_events WHERE vin = %s", (vin,))
        cur.execute("DELETE FROM trips WHERE vin = %s", (vin,))
    conn.commit()


def insert_trips(conn, trips: list[dict]):
    """Batch-insert trip rows."""
    if not trips:
        return
    sql = """
        INSERT INTO trips
            (trip_id, vin, start_ts, end_ts, start_lat, start_lon,
             end_lat, end_lon, distance_km, duration_min, avg_speed_kmh,
             fuel_used_l, energy_used_kwh, idle_duration_min)
        VALUES %s
    """
    rows = [
        (
            t["trip_id"], t["vin"],
            t["start_ts"], t["end_ts"],
            t["start_lat"], t["start_lon"],
            t["end_lat"], t["end_lon"],
            round(t["distance_km"], 2),
            t["duration_min"],
            t["avg_speed_kmh"],
            t["fuel_used_l"],
            t["energy_used_kwh"],
            t["idle_duration_min"],
        )
        for t in trips
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=INSERT_BATCH_SIZE)
    conn.commit()


def insert_idle_events(conn, idles: list[dict]):
    """Batch-insert idle event rows."""
    if not idles:
        return
    sql = """
        INSERT INTO idle_events
            (idle_id, vin, trip_id, start_ts, end_ts, duration_min,
             lat, lon, fuel_burned_l, energy_burned_kwh, idle_type)
        VALUES %s
    """
    rows = [
        (
            i["idle_id"], i["vin"], i["trip_id"],
            i["start_ts"], i["end_ts"],
            i["duration_min"],
            i["lat"], i["lon"],
            i["fuel_burned_l"],
            i["energy_burned_kwh"],
            i["idle_type"],
        )
        for i in idles
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=INSERT_BATCH_SIZE)
    conn.commit()


# ============================================================================
# MAIN — orchestration
# ============================================================================

def process_vehicle(conn, vin: str, fuel_type: str, dry_run: bool = False) -> tuple[int, int]:
    """Full pipeline for one vehicle: fetch → segment → write.
    Returns (n_trips, n_idles)."""
    t0 = time.time()
    rows = fetch_telemetry_for_vin(conn, vin)
    fetch_sec = time.time() - t0
    if not rows:
        return 0, 0

    t1 = time.time()
    trips, idles = segment_vehicle(rows, vin, fuel_type)
    seg_sec = time.time() - t1

    if dry_run:
        print(f"  [DRY RUN] {vin}: {len(trips)} trips, {len(idles)} idle events "
              f"(fetch={fetch_sec:.1f}s, segment={seg_sec:.1f}s, rows={len(rows):,})")
        for t in trips[:3]:
            print(f"    trip: {t['start_ts']} → {t['end_ts']}  "
                  f"dist={t['distance_km']:.1f} km  dur={t['duration_min']:.1f} min  "
                  f"idle_in_trip={t['idle_duration_min']:.1f} min")
        for i in idles[:3]:
            print(f"    idle: {i['start_ts']} → {i['end_ts']}  "
                  f"type={i['idle_type']}  dur={i['duration_min']:.1f} min")
        return len(trips), len(idles)

    # Idempotent: clear old results, then insert fresh
    t2 = time.time()
    clear_results_for_vin(conn, vin)
    insert_trips(conn, trips)
    insert_idle_events(conn, idles)
    write_sec = time.time() - t2

    print(f"  {vin}: {len(trips)} trips, {len(idles)} idles "
          f"({len(rows):,} rows, fetch={fetch_sec:.1f}s seg={seg_sec:.2f}s write={write_sec:.1f}s)")

    return len(trips), len(idles)


def _process_vehicle_standalone(vin: str, fuel_type: str, dry_run: bool) -> tuple[str, int, int]:
    """Thread-safe wrapper: creates its own connection, processes one vehicle,
    closes connection. Used by ThreadPoolExecutor."""
    conn = get_connection()
    try:
        n_trips, n_idles = process_vehicle(conn, vin, fuel_type, dry_run=dry_run)
        return vin, n_trips, n_idles
    except Exception as e:
        print(f"  ERROR on {vin}: {e}")
        return vin, 0, 0
    finally:
        conn.close()


# Number of concurrent workers (each gets its own DB connection).
# Each worker uses its own database connection; keep concurrency bounded.
MAX_WORKERS = 6


def main():
    parser = argparse.ArgumentParser(
        description="M4: Trip & Idle Segmentation Engine — "
                    "reads telemetry_events, writes trips + idle_events"
    )
    parser.add_argument("--vin", type=str, default=None,
                        help="Process only this VIN (for debugging / spot-checks)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print segmentation results without writing to DB")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS,
                        help=f"Number of concurrent workers (default: {MAX_WORKERS})")
    args = parser.parse_args()

    print("=" * 60)
    print("M4: Trip & Idle Segmentation Engine")
    print("=" * 60)

    start_time = time.time()

    if args.vin:
        # Single vehicle mode — sequential, one connection
        conn = get_connection()
        print("Connected to PostgreSQL")

        with conn.cursor() as cur:
            cur.execute("SELECT fuel_type FROM vehicles WHERE vin = %s", (args.vin,))
            result = cur.fetchone()
            if not result:
                print(f"ERROR: VIN '{args.vin}' not found in vehicles table.")
                sys.exit(1)
            fuel_type = result[0]

        print(f"\nProcessing single vehicle: {args.vin} ({fuel_type})")
        n_trips, n_idles = process_vehicle(conn, args.vin, fuel_type, dry_run=args.dry_run)
        conn.close()
        total_trips, total_idles = n_trips, n_idles

    else:
        # All vehicles — concurrent with ThreadPoolExecutor
        conn = get_connection()
        print("Connected to PostgreSQL")
        vin_list = fetch_distinct_vins(conn)
        conn.close()
        print(f"\nFound {len(vin_list)} vehicles with telemetry data")
        print(f"Processing with {args.workers} concurrent workers...\n")

        total_trips = 0
        total_idles = 0
        completed = 0

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(_process_vehicle_standalone, vin, fuel_type, args.dry_run): vin
                for vin, fuel_type in vin_list
            }
            for future in as_completed(futures):
                vin, n_trips, n_idles = future.result()
                total_trips += n_trips
                total_idles += n_idles
                completed += 1
                if completed % 10 == 0 or completed == len(vin_list):
                    elapsed = time.time() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    eta = (len(vin_list) - completed) / rate if rate > 0 else 0
                    print(f"\n  [{completed}/{len(vin_list)}] "
                          f"{total_trips:,} trips, {total_idles:,} idles "
                          f"({elapsed:.0f}s elapsed, ~{eta:.0f}s remaining)\n")

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"DONE in {elapsed:.1f}s: {total_trips:,} trips + {total_idles:,} idle events "
          f"{'(dry run — nothing written)' if args.dry_run else 'written to PostgreSQL'}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
