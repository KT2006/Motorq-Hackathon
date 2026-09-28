import datetime
import psycopg2
import os
from dotenv import load_dotenv
from segment import process_vehicle

load_dotenv("../../.env")
conn = psycopg2.connect(os.getenv("POSTGRES_URL"))
conn.autocommit = False
cur = conn.cursor()

# Get a valid vin
cur.execute("SELECT vin, fuel_type FROM vehicles LIMIT 1;")
row = cur.fetchone()
vin = row[0]
fuel_type = row[1]

print("--- Edge Case 1: Zero telemetry events ---")
# Pick a date far in the future
day = datetime.date(2030, 1, 1)
try:
    # Just calling process_vehicle. It fetches ALL rows for the vin.
    # To test zero rows, we can pass a fake VIN.
    n_trips, n_idles = process_vehicle(conn, "FAKE-VIN-1234", fuel_type)
    print(f"Success! Processed smoothly. Returned {n_trips} trips, {n_idles} idles.")
except Exception as e:
    print(f"Failed: {e}")

print("\n--- Edge Case 2: Unclosed trip ---")
# We will mock the database by inserting fake unclosed trip data for a new day
mock_day = datetime.date(2030, 1, 2)
# insert an ignition on and speed > 0, then nothing else
cur.execute("""
    INSERT INTO telemetry_events (vin, ts, seq, ignition_status, speed_kmh, lat, lon, odo_km)
    VALUES (%s, %s, %s, true, 50.0, 0.0, 0.0, 1000.0)
""", (vin, datetime.datetime(2030, 1, 2, 12, 0, 0), 1))
conn.commit()

try:
    n_trips, n_idles = process_vehicle(conn, vin, fuel_type)
    print(f"Processed smoothly. Returned {n_trips} trips, {n_idles} idles.")
except Exception as e:
    print(f"Failed: {e}")

# Cleanup EC2 to isolate EC3
cur.execute("DELETE FROM telemetry_events WHERE ts = '2030-01-02 12:00:00'")
conn.commit()

print("\n--- Edge Case 3: Duplicate timestamps ---")
mock_day_3 = datetime.date(2030, 1, 3)
cur.execute("""
    INSERT INTO telemetry_events (vin, ts, seq, ignition_status, speed_kmh, lat, lon, odo_km)
    VALUES 
    (%s, %s, %s, true, 50.0, 0.0, 0.0, 1000.0),
    (%s, %s, %s, true, 0.0, 0.0, 0.0, 1000.5)
""", (
    vin, datetime.datetime(2030, 1, 3, 12, 0, 0), 1,
    vin, datetime.datetime(2030, 1, 3, 12, 0, 0), 2
))
conn.commit()

try:
    n_trips, n_idles = process_vehicle(conn, vin, fuel_type)
    print(f"Processed smoothly. Returned {n_trips} trips, {n_idles} idles.")
except Exception as e:
    print(f"Failed: {e}")

# Clean up
cur.execute("DELETE FROM telemetry_events WHERE ts >= '2030-01-01'")
conn.commit()
conn.close()
