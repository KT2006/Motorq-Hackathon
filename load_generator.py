import json
import time
import uuid
from multiprocessing import Process
from kafka import KafkaProducer

def json_serializer(v):
    return json.dumps(v).encode('utf-8')

def worker(topic, bootstrap, count):
    producer = KafkaProducer(
        bootstrap_servers=bootstrap,
        value_serializer=json_serializer,
        batch_size=32768,
        linger_ms=10,
    )
    base_event = {
        'vin': '1HGBH41JXMN109186',
        'ts': '2026-09-30T10:00:00Z',
        'lat': 37.7749,
        'lon': -122.4194,
        'speed_kmh': 65.0,
        'odo_km': 15000.0,
        'ignition_status': True,
        'fuel_level_pct': 85.0,
        'seq': 1
    }
    vin_prefix = str(uuid.uuid4())[:8]
    for i in range(count):
        e = base_event.copy()
        e['vin'] = f'{vin_prefix}{i%20000:09d}'
        e['seq'] = i
        producer.send(topic, e)
    producer.flush()

if __name__ == '__main__':
    processes = []
    for _ in range(8):
        p = Process(target=worker, args=('telemetry', 'localhost:9092', 62500))
        p.start()
        processes.append(p)
    
    start = time.time()
    for p in processes:
        p.join()
    end = time.time()
    print(f'Pushed 500,000 events to Kafka in {end - start:.2f} seconds')
