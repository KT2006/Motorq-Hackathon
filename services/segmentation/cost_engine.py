"""
M5: Cost & Utilisation Calculation Engine
==========================================
Consumes trips + idle_events (from M4) and reference tables to produce
cost_summary_daily — one row per vehicle per day answering:
"Where are we losing money, and how much can we save?"

Two parts:
  Part 1: Daily rollup job — aggregates trips/idles into cost numbers
  Part 2: Top-K "worst offenders" scoring — weighted ranking vs naive threshold

Usage:
    # Full rollup (all vehicles, all days):
    python cost_engine.py

    # Specific date range:
    python cost_engine.py --start 2026-08-28 --end 2026-09-26

    # Dry run:
    python cost_engine.py --dry-run

    # Top-K offenders report:
    python cost_engine.py --top-k 10

    # Top-K with baseline comparison:
    python cost_engine.py --top-k 10 --compare

Requires: POSTGRES_URL in ../../.env
"""

import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load environment
# ---------------------------------------------------------------------------
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)

POSTGRES_URL = os.getenv("POSTGRES_URL", "")

# ---------------------------------------------------------------------------
# Scoring weights for the weighted top-K offender ranking.
# These are tunable — equal weights is defensible as a starting point.
# w1: raw idle cost (INR) — captures absolute waste
# w2: idle % of active time — captures relative inefficiency
# w3: raw idle minutes — captures time waste independent of cost
# ---------------------------------------------------------------------------
W_IDLE_COST = 1.0
W_IDLE_PCT = 1.0
W_IDLE_MIN = 1.0

# Naive threshold for baseline comparison (minutes/day)
NAIVE_IDLE_THRESHOLD_MIN = 60.0

# Available minutes per day (24h default; could be a shift window)
AVAILABLE_MIN_PER_DAY = 24 * 60  # 1440 minutes


# ============================================================================
# DATABASE
# ============================================================================

def get_connection():
    """Get a raw psycopg2 connection from POSTGRES_URL."""
    if not POSTGRES_URL:
        raise RuntimeError(
            "POSTGRES_URL not set. Add it to your .env file:\n"
            "  POSTGRES_URL=postgresql://user:password@host:5432/dbname"
        )
    url = POSTGRES_URL.replace("postgres://", "postgresql://")
    conn = psycopg2.connect(url)
    conn.set_session(readonly=False, autocommit=False)
    return conn


def seed_idle_burn_rates(conn):
    """Seed idle_burn_rate_reference if empty. Values match the simulator's
    assumptions for internal consistency. Source citations included."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM idle_burn_rate_reference")
        if cur.fetchone()[0] > 0:
            return  # already seeded

        rates = [
            ("petrol_light",  0.6, "US DOE ORNL Fact #861 — avg 0.5-0.7 L/h for light-duty petrol"),
            ("petrol_heavy",  1.2, "US DOE ORNL — heavy-duty petrol trucks ~1.0-1.5 L/h"),
            ("diesel_light",  0.5, "Argonne National Lab — light-duty diesel ~0.4-0.6 L/h"),
            ("diesel_heavy",  1.0, "Argonne National Lab — heavy-duty diesel ~0.8-1.2 L/h"),
            ("hybrid_light",  0.3, "Auto-start/stop reduces idle burn ~40-60% vs pure ICE"),
            ("ev_light",      0.9, "EV HVAC draw ~0.8-1.2 kW avg; used kWh/h as equivalent unit"),
        ]
        for vc, rate, citation in rates:
            cur.execute("""
                INSERT INTO idle_burn_rate_reference (vehicle_class, idle_burn_rate, source_citation)
                VALUES (%s, %s, %s)
                ON CONFLICT (vehicle_class) DO NOTHING
            """, (vc, rate, citation))
    conn.commit()
    print("  Seeded idle_burn_rate_reference with 6 vehicle classes")


# ============================================================================
# PART 1: DAILY ROLLUP
# ============================================================================

ROLLUP_SQL = """
WITH trip_daily AS (
    -- Aggregate trips per vehicle per day
    SELECT
        v.vehicle_id,
        t.start_ts::date AS summary_date,
        COALESCE(SUM(t.distance_km), 0)    AS total_distance_km,
        COALESCE(SUM(t.duration_min), 0)    AS total_drive_min,
        COALESCE(SUM(t.fuel_used_l), 0)     AS total_fuel_used_l,
        COALESCE(SUM(t.energy_used_kwh), 0) AS total_energy_used_kwh
    FROM trips t
    JOIN vehicles v ON v.vin = t.vin
    GROUP BY v.vehicle_id, t.start_ts::date
),
idle_daily AS (
    -- Aggregate idle events per vehicle per day
    SELECT
        v.vehicle_id,
        ie.start_ts::date AS summary_date,
        COALESCE(SUM(ie.duration_min), 0)       AS total_idle_min,
        COALESCE(SUM(ie.fuel_burned_l), 0)      AS total_idle_fuel_l,
        COALESCE(SUM(ie.energy_burned_kwh), 0)  AS total_idle_energy_kwh
    FROM idle_events ie
    JOIN vehicles v ON v.vin = ie.vin
    GROUP BY v.vehicle_id, ie.start_ts::date
),
combined AS (
    SELECT
        COALESCE(td.vehicle_id, id.vehicle_id) AS vehicle_id,
        COALESCE(td.summary_date, id.summary_date) AS summary_date,
        COALESCE(td.total_distance_km, 0)   AS total_distance_km,
        COALESCE(td.total_drive_min, 0)     AS total_drive_min,
        COALESCE(id.total_idle_min, 0)      AS total_idle_min,
        COALESCE(td.total_fuel_used_l, 0)   AS total_fuel_used_l,
        COALESCE(td.total_energy_used_kwh, 0) AS total_energy_used_kwh,
        COALESCE(id.total_idle_fuel_l, 0)   AS total_idle_fuel_l,
        COALESCE(id.total_idle_energy_kwh, 0) AS total_idle_energy_kwh
    FROM trip_daily td
    FULL OUTER JOIN idle_daily id
        ON td.vehicle_id = id.vehicle_id
        AND td.summary_date = id.summary_date
)
SELECT
    c.vehicle_id,
    c.summary_date,
    c.total_distance_km,
    c.total_drive_min,
    c.total_idle_min,
    %(available_min)s AS available_min,

    -- Fuel cost: fuel consumed during trips × price per unit
    CASE
        WHEN v.fuel_type = 'ev' THEN
            c.total_energy_used_kwh * COALESCE(fp.price_per_unit, 10.0)
        ELSE
            c.total_fuel_used_l * COALESCE(fp.price_per_unit, 100.0)
    END AS fuel_cost,

    -- Idle cost: fuel/energy burned while idling × price per unit
    CASE
        WHEN v.fuel_type = 'ev' THEN
            c.total_idle_energy_kwh * COALESCE(fp.price_per_unit, 10.0)
        ELSE
            c.total_idle_fuel_l * COALESCE(fp.price_per_unit, 100.0)
    END AS idle_cost,

    -- Utilisation percentage
    CASE
        WHEN %(available_min)s > 0 THEN
            LEAST(100.0, c.total_drive_min / %(available_min)s * 100.0)
        ELSE 0.0
    END AS utilisation_pct

FROM combined c
JOIN vehicles v ON v.vehicle_id = c.vehicle_id
JOIN fleets f ON f.fleet_id = v.fleet_id
LEFT JOIN LATERAL (
    -- Get the most recent fuel price on or before the summary date
    SELECT price_per_unit
    FROM fuel_price_reference fpr
    WHERE fpr.fuel_type = v.fuel_type
      AND fpr.region = 'India'
      AND fpr.effective_date <= c.summary_date
    ORDER BY fpr.effective_date DESC
    LIMIT 1
) fp ON TRUE
ORDER BY c.vehicle_id, c.summary_date
"""


def run_rollup(conn, start_date=None, end_date=None, dry_run=False):
    """Execute the daily rollup and upsert into cost_summary_daily."""
    t0 = time.time()

    with conn.cursor() as cur:
        cur.execute(ROLLUP_SQL, {"available_min": AVAILABLE_MIN_PER_DAY})
        rows = cur.fetchall()
        col_names = [desc[0] for desc in cur.description]

    fetch_sec = time.time() - t0
    print(f"  Rollup query returned {len(rows):,} rows in {fetch_sec:.1f}s")

    # Filter by date range if specified
    if start_date or end_date:
        filtered = []
        for r in rows:
            row_date = r[1]  # summary_date is index 1
            if start_date and row_date < start_date:
                continue
            if end_date and row_date > end_date:
                continue
            filtered.append(r)
        print(f"  Filtered to {len(filtered):,} rows for date range {start_date} → {end_date}")
        rows = filtered

    if not rows:
        print("  No data to write.")
        return 0

    if dry_run:
        print(f"\n  [DRY RUN] Would write {len(rows):,} rows to cost_summary_daily")
        # Show a few samples
        for r in rows[:5]:
            print(f"    vehicle={str(r[0])[:8]}  date={r[1]}  "
                  f"dist={float(r[2]):.1f}km  drive={float(r[3]):.1f}min  "
                  f"idle={float(r[4]):.1f}min  fuel_cost=₹{float(r[6]):.2f}  "
                  f"idle_cost=₹{float(r[7]):.2f}  util={float(r[8]):.1f}%")
        return len(rows)

    # Upsert into cost_summary_daily
    t1 = time.time()
    upsert_sql = """
        INSERT INTO cost_summary_daily
            (vehicle_id, summary_date, total_distance_km, total_drive_min,
             total_idle_min, available_min, fuel_cost, idle_cost, utilisation_pct)
        VALUES %s
        ON CONFLICT (vehicle_id, summary_date) DO UPDATE SET
            total_distance_km = EXCLUDED.total_distance_km,
            total_drive_min   = EXCLUDED.total_drive_min,
            total_idle_min    = EXCLUDED.total_idle_min,
            available_min     = EXCLUDED.available_min,
            fuel_cost         = EXCLUDED.fuel_cost,
            idle_cost         = EXCLUDED.idle_cost,
            utilisation_pct   = EXCLUDED.utilisation_pct
    """
    # Prepare tuples — ensure proper types
    upsert_rows = [
        (
            r[0],                   # vehicle_id
            r[1],                   # summary_date
            round(float(r[2]), 2),  # total_distance_km
            round(float(r[3]), 2),  # total_drive_min
            round(float(r[4]), 2),  # total_idle_min
            round(float(r[5]), 2),  # available_min
            round(float(r[6]), 2),  # fuel_cost
            round(float(r[7]), 2),  # idle_cost
            round(float(r[8]), 2),  # utilisation_pct
        )
        for r in rows
    ]

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, upsert_sql, upsert_rows, page_size=500)
    conn.commit()
    write_sec = time.time() - t1

    print(f"  Upserted {len(upsert_rows):,} rows into cost_summary_daily in {write_sec:.1f}s")
    return len(upsert_rows)


# ============================================================================
# PART 2: TOP-K OFFENDER SCORING
# ============================================================================

TOP_K_WEIGHTED_SQL = """
WITH daily_scores AS (
    SELECT
        cs.vehicle_id,
        v.vin,
        v.fuel_type,
        f.fleet_name,
        cs.summary_date,
        cs.total_drive_min,
        cs.total_idle_min,
        cs.idle_cost,
        cs.fuel_cost,
        cs.utilisation_pct,
        -- Idle percentage of active time
        CASE
            WHEN (cs.total_drive_min + cs.total_idle_min) > 0 THEN
                cs.total_idle_min / (cs.total_drive_min + cs.total_idle_min) * 100.0
            ELSE 0.0
        END AS idle_pct_of_active
    FROM cost_summary_daily cs
    JOIN vehicles v ON v.vehicle_id = cs.vehicle_id
    JOIN fleets f ON f.fleet_id = v.fleet_id
    WHERE cs.summary_date BETWEEN %(start_date)s AND %(end_date)s
),
vehicle_agg AS (
    SELECT
        vehicle_id,
        vin,
        fuel_type,
        fleet_name,
        COUNT(*)                        AS days_active,
        ROUND(AVG(total_drive_min)::numeric, 1)  AS avg_drive_min,
        ROUND(AVG(total_idle_min)::numeric, 1)   AS avg_idle_min,
        ROUND(SUM(idle_cost)::numeric, 2)        AS total_idle_cost,
        ROUND(SUM(fuel_cost)::numeric, 2)        AS total_fuel_cost,
        ROUND(AVG(utilisation_pct)::numeric, 1)  AS avg_util_pct,
        ROUND(AVG(idle_pct_of_active)::numeric, 1) AS avg_idle_pct
    FROM daily_scores
    GROUP BY vehicle_id, vin, fuel_type, fleet_name
),
scored AS (
    SELECT
        *,
        -- Weighted score (normalized components)
        -- Each component is scaled to roughly [0, 1] then weighted
        (
            %(w_cost)s  * (total_idle_cost / GREATEST(NULLIF((SELECT MAX(total_idle_cost) FROM vehicle_agg), 0), 1)) +
            %(w_pct)s   * (avg_idle_pct / 100.0) +
            %(w_min)s   * (avg_idle_min / GREATEST(NULLIF((SELECT MAX(avg_idle_min) FROM vehicle_agg), 0), 1))
        ) AS weighted_score,
        -- Naive flag: avg idle > threshold
        CASE WHEN avg_idle_min > %(threshold)s THEN TRUE ELSE FALSE END AS naive_flagged
    FROM vehicle_agg
)
SELECT * FROM scored
ORDER BY weighted_score DESC
LIMIT %(k)s
"""

NAIVE_FLAGGED_SQL = """
SELECT
    v.vehicle_id,
    v.vin,
    v.fuel_type,
    ROUND(AVG(cs.total_idle_min)::numeric, 1) AS avg_idle_min,
    ROUND(SUM(cs.idle_cost)::numeric, 2) AS total_idle_cost
FROM cost_summary_daily cs
JOIN vehicles v ON v.vehicle_id = cs.vehicle_id
WHERE cs.summary_date BETWEEN %(start_date)s AND %(end_date)s
GROUP BY v.vehicle_id, v.vin, v.fuel_type
HAVING AVG(cs.total_idle_min) > %(threshold)s
ORDER BY AVG(cs.total_idle_min) DESC
"""


def run_top_k(conn, k=10, start_date=None, end_date=None, compare=False):
    """Run the weighted top-K offender ranking, optionally comparing to naive baseline."""
    with conn.cursor() as cur:
        # Get date range from data if not specified
        if not start_date or not end_date:
            cur.execute("SELECT MIN(summary_date), MAX(summary_date) FROM cost_summary_daily")
            row = cur.fetchone()
            start_date = start_date or row[0]
            end_date = end_date or row[1]

    print(f"\n{'='*70}")
    print(f"TOP-{k} WORST IDLE OFFENDERS  ({start_date} → {end_date})")
    print(f"Scoring: w_cost={W_IDLE_COST}, w_pct={W_IDLE_PCT}, w_min={W_IDLE_MIN}")
    print(f"{'='*70}")

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(TOP_K_WEIGHTED_SQL, {
            "start_date": start_date,
            "end_date": end_date,
            "k": k,
            "w_cost": W_IDLE_COST,
            "w_pct": W_IDLE_PCT,
            "w_min": W_IDLE_MIN,
            "threshold": NAIVE_IDLE_THRESHOLD_MIN,
        })
        top_k_results = cur.fetchall()

    print(f"\n{'Rank':<5} {'VIN':<20} {'Fuel':<8} {'Score':<8} "
          f"{'Avg Idle':<10} {'Idle%':<8} {'Idle Cost':<12} "
          f"{'Avg Drive':<10} {'Util%':<8} {'Naive?':<7}")
    print("-" * 106)

    for i, r in enumerate(top_k_results, 1):
        print(f"{i:<5} {r['vin']:<20} {r['fuel_type']:<8} "
              f"{float(r['weighted_score']):<8.3f} "
              f"{float(r['avg_idle_min']):<10.1f} "
              f"{float(r['avg_idle_pct']):<8.1f} "
              f"₹{float(r['total_idle_cost']):<11.2f} "
              f"{float(r['avg_drive_min']):<10.1f} "
              f"{float(r['avg_util_pct']):<8.1f} "
              f"{'YES' if r['naive_flagged'] else 'NO':<7}")

    if compare:
        _run_comparison(conn, top_k_results, start_date, end_date)

    return top_k_results


def _run_comparison(conn, top_k_results, start_date, end_date):
    """Compare weighted ranking vs naive threshold — find disagreements."""
    print(f"\n{'='*70}")
    print(f"BASELINE COMPARISON: Naive threshold ({NAIVE_IDLE_THRESHOLD_MIN} min/day) vs Weighted Score")
    print(f"{'='*70}")

    # Get naive-flagged vehicles
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(NAIVE_FLAGGED_SQL, {
            "start_date": start_date,
            "end_date": end_date,
            "threshold": NAIVE_IDLE_THRESHOLD_MIN,
        })
        naive_results = cur.fetchall()

    naive_vins = {r["vin"] for r in naive_results}
    weighted_vins = {r["vin"] for r in top_k_results}

    # Find disagreements
    in_weighted_not_naive = [r for r in top_k_results if not r["naive_flagged"]]
    in_naive_not_weighted = [r for r in naive_results if r["vin"] not in weighted_vins]

    print(f"\n  Naive threshold flags: {len(naive_vins)} vehicles")
    print(f"  Weighted top-K flags:  {len(weighted_vins)} vehicles")
    print(f"  Agreement:             {len(naive_vins & weighted_vins)} vehicles in both")

    if in_weighted_not_naive:
        print(f"\n  ⚠ Vehicles in weighted top-K but MISSED by naive threshold:")
        for r in in_weighted_not_naive[:3]:
            print(f"    → {r['vin']} ({r['fuel_type']}): "
                  f"avg idle = {float(r['avg_idle_min']):.1f} min (under {NAIVE_IDLE_THRESHOLD_MIN} threshold), "
                  f"BUT idle% = {float(r['avg_idle_pct']):.1f}% of active time, "
                  f"idle cost = ₹{float(r['total_idle_cost']):.2f}")
            print(f"      → The naive approach misses this because {float(r['avg_idle_min']):.1f} min < "
                  f"{NAIVE_IDLE_THRESHOLD_MIN} min cutoff,")
            print(f"        but idling is {float(r['avg_idle_pct']):.1f}% of its total active time "
                  f"— a disproportionately idle vehicle.")

    if in_naive_not_weighted:
        print(f"\n  ℹ Vehicles flagged by naive but NOT in weighted top-{len(top_k_results)}:")
        for r in in_naive_not_weighted[:3]:
            print(f"    → {r['vin']} ({r['fuel_type']}): "
                  f"avg idle = {float(r['avg_idle_min']):.1f} min, "
                  f"idle cost = ₹{float(r['total_idle_cost']):.2f}")

    print()


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="M5: Cost & Utilisation Calculation Engine"
    )
    parser.add_argument("--start", type=str, default=None,
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None,
                        help="End date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print results without writing to DB")
    parser.add_argument("--top-k", type=int, default=None,
                        help="Run top-K offender ranking after rollup")
    parser.add_argument("--compare", action="store_true",
                        help="Compare weighted vs naive baseline (use with --top-k)")
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start) if args.start else None
    end_date = date.fromisoformat(args.end) if args.end else None

    print("=" * 60)
    print("M5: Cost & Utilisation Calculation Engine")
    print("=" * 60)

    conn = get_connection()
    print("Connected to Supabase/Postgres")

    # Seed reference data if needed
    seed_idle_burn_rates(conn)

    # Part 1: Daily rollup
    start_time = time.time()
    n_rows = run_rollup(conn, start_date, end_date, dry_run=args.dry_run)
    elapsed = time.time() - start_time

    print(f"\n  Rollup complete in {elapsed:.1f}s — {n_rows:,} rows")

    # Part 2: Top-K ranking (if requested)
    if args.top_k:
        run_top_k(conn, k=args.top_k, start_date=start_date,
                  end_date=end_date, compare=args.compare)

    conn.close()
    print(f"\n{'=' * 60}")
    print("DONE")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
