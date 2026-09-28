import psycopg2, os
from dotenv import load_dotenv
from segment import process_vehicle

load_dotenv("../../.env")
conn = psycopg2.connect(os.getenv("POSTGRES_URL"))
conn.autocommit = False
cur = conn.cursor()

cur.execute("SELECT vin, COUNT(*) FROM trips GROUP BY vin ORDER BY COUNT(*) DESC LIMIT 5;")
rows = cur.fetchall()
print("Initial Trip Counts:")
for row in rows:
    print(f"VIN: {row[0]}, Trips: {row[1]}")

vin_to_test = rows[0][0]
initial_count = rows[0][1]
cur.execute("SELECT fuel_type FROM vehicles WHERE vin = %s", (vin_to_test,))
fuel_type = cur.fetchone()[0]

print(f"\nRe-running segmentation for {vin_to_test}...")
process_vehicle(conn, vin_to_test, fuel_type)

cur.execute("SELECT COUNT(*) FROM trips WHERE vin = %s", (vin_to_test,))
new_count = cur.fetchone()[0]
print(f"\nNew Trip Count for {vin_to_test}: {new_count}")

if initial_count == new_count:
    print("SUCCESS: Idempotency confirmed. Count did not change.")
else:
    print("FAILURE: Duplicate trips detected!")
