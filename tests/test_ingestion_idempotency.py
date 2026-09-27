import pytest
import os
import psycopg2
from dotenv import load_dotenv

def get_connection():
    load_dotenv(os.path.join(os.path.dirname(__file__), '../.env'))
    url = os.getenv("POSTGRES_URL").replace("postgres://", "postgresql://")
    conn = psycopg2.connect(url)
    conn.set_session(readonly=False, autocommit=False)
    return conn

def insert_telemetry_event(conn, vin: str, ts: str, seq: int, lat: float, lon: float, speed_kmh: float, odo_km: float, ignition: bool):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO telemetry_events 
                (vin, ts, seq, lat, lon, speed_kmh, odo_km, ignition_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (vin, ts, seq) DO NOTHING
        """, (vin, ts, seq, lat, lon, speed_kmh, odo_km, ignition))
    conn.commit()

def query_telemetry_events(conn, vin: str):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT seq, ts FROM telemetry_events 
            WHERE vin = %s 
            ORDER BY ts ASC, seq ASC
        """, (vin,))
        return [{"seq": row[0], "ts": row[1]} for row in cur.fetchall()]

def test_ingestion_is_idempotent():
    conn = get_connection()
    vin = "TESTVIN9999999999"
    
    # Clean up any existing test data
    with conn.cursor() as cur:
        cur.execute("DELETE FROM telemetry_events WHERE vin = %s", (vin,))
    conn.commit()
    
    # 1. Insert a normal event
    insert_telemetry_event(conn, vin, "2026-09-25T10:15:02Z", 1, 12.0, 77.0, 30.0, 100.0, True)
    
    # 2. Insert the SAME event again (simulating duplicate delivery)
    insert_telemetry_event(conn, vin, "2026-09-25T10:15:02Z", 1, 12.0, 77.0, 30.0, 100.0, True)
    
    # 3. Insert an out-of-order event (earlier seq arriving late)
    insert_telemetry_event(conn, vin, "2026-09-25T10:15:01Z", 0, 12.0, 77.0, 20.0, 99.9, True)
    
    rows = query_telemetry_events(conn, vin)
    
    # Clean up test data
    with conn.cursor() as cur:
        cur.execute("DELETE FROM telemetry_events WHERE vin = %s", (vin,))
    conn.commit()
    conn.close()
    
    assert len(rows) == 2  # duplicate collapsed, out-of-order one accepted
    assert rows[0]["seq"] == 0  # correctly ordered by ts, not insertion order
