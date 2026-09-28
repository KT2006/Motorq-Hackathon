import psycopg2, os, json, time
from kafka import KafkaProducer
from dotenv import load_dotenv

load_dotenv(".env")
conn = psycopg2.connect(os.getenv("POSTGRES_URL"))
cur = conn.cursor()

import datetime
rows = []
base_time = datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)
for i in range(5):
    rows.append((
        "TESTVINIDEMPOTENT",
        base_time + datetime.timedelta(minutes=i),
        i + 1,
        True,
        50.0 + i,
        12.9,
        80.1,
        1000.0 + (i * 0.5)
    ))

columns = ["vin", "ts", "seq", "ignition_status", "speed_kmh", "lat", "lon", "odo_km"]

producer = KafkaProducer(
    bootstrap_servers='localhost:9092',
    value_serializer=lambda v: json.dumps(v, default=str).encode('utf-8')
)

for row in rows:
    event = dict(zip(columns, row))
    producer.send('telemetry', value=event)
    time.sleep(0.01)  # small delay so it visibly streams rather than dumping instantly

producer.flush()
print(f"Published {len(rows)} events to 'telemetry' topic.")
