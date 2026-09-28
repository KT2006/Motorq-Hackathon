import psycopg2, os, json
from kafka import KafkaConsumer
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
import redis

load_dotenv(".env")
conn = psycopg2.connect(os.getenv("POSTGRES_URL"))
conn.autocommit = False
cur = conn.cursor()

# C2: Connect to Redis
redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)

consumer = KafkaConsumer(
    'telemetry',
    bootstrap_servers='localhost:9092',
    value_deserializer=lambda m: json.loads(m.decode('utf-8')),
    auto_offset_reset='latest',
    group_id='ingestion-consumer-2'
)

count = 0
for message in consumer:
    e = message.value
    cur.execute("""
        INSERT INTO telemetry_events (vin, ts, seq, ignition_status, speed_kmh, lat, lon, odo_km)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (vin, ts, seq) DO NOTHING
    """, (e['vin'], e['ts'], e['seq'], e['ignition_status'], e['speed_kmh'], e['lat'], e['lon'], e['odo_km']))
    conn.commit()
    
    # C2: Update live vehicle status in Redis
    redis_client.hset(f"vehicle:{e['vin']}:status", mapping={
        "lat": e['lat'],
        "lon": e['lon'],
        "speed_kmh": e['speed_kmh'],
        "ignition_status": str(e['ignition_status']),
        "last_seen": e['ts']
    })
    redis_client.expire(f"vehicle:{e['vin']}:status", 86400)
    
    count += 1
    if count % 5 == 0:
        print(f"Consumed and wrote {count} events so far...", flush=True)
