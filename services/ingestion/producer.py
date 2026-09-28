"""Small deterministic producer used to demonstrate live-status updates."""

import json
import os
import time
from datetime import datetime, timezone

from kafka import KafkaProducer

BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")
TOPIC = os.getenv("TELEMETRY_TOPIC", "telemetry")
VIN = os.getenv("LIVE_DEMO_VIN", "")
EVENT_COUNT = int(os.getenv("LIVE_DEMO_EVENT_COUNT", "30"))
INTERVAL_SECONDS = float(os.getenv("LIVE_DEMO_INTERVAL_SECONDS", "1"))

if len(VIN) != 17:
    raise RuntimeError("Set LIVE_DEMO_VIN to the 17-character VIN shown on a vehicle detail page.")

producer = KafkaProducer(
    bootstrap_servers=BOOTSTRAP_SERVERS,
    value_serializer=lambda event: json.dumps(event).encode("utf-8"),
)

for sequence in range(EVENT_COUNT):
    event = {
        "vin": VIN,
        "ts": datetime.now(timezone.utc).isoformat(),
        "seq": int(time.time() * 1000) + sequence,
        "ignition_status": True,
        "speed_kmh": round(25 + sequence * 0.4, 1),
        "lat": round(12.9716 + sequence * 0.0001, 6),
        "lon": round(77.5946 + sequence * 0.0001, 6),
        "odo_km": round(1000 + sequence * 0.08, 2),
        "evt": "TRIP_START" if sequence == 0 else None,
    }
    producer.send(TOPIC, key=VIN.encode("utf-8"), value=event)
    producer.flush()
    print(f"Published {sequence + 1}/{EVENT_COUNT}: {VIN} @ {event['speed_kmh']} km/h", flush=True)
    time.sleep(INTERVAL_SECONDS)

producer.close()
