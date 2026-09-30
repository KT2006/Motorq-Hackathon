"""Idempotent, batched telemetry consumer for the live-status pipeline."""

import json
import logging
import os
import time
from datetime import datetime
from typing import Literal

import psycopg2
import psycopg2.extras
import redis
from dotenv import load_dotenv
from kafka import KafkaConsumer
from kafka.errors import KafkaError
from pydantic import BaseModel, Field, ValidationError

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("ingestion")

POSTGRES_URL = os.environ["POSTGRES_URL"].replace("postgres://", "postgresql://")
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
TELEMETRY_TOPIC = os.getenv("TELEMETRY_TOPIC", "telemetry")
DLQ_TOPIC = os.getenv("DLQ_TOPIC", "telemetry-dlq")
CONSUMER_GROUP = os.getenv("KAFKA_CONSUMER_GROUP", "telemetry-ingestion-v1")
BATCH_SIZE = int(os.getenv("INGEST_BATCH_SIZE", "500"))
POLL_TIMEOUT_MS = int(os.getenv("INGEST_POLL_TIMEOUT_MS", "1000"))
LIVE_STATUS_TTL_SEC = int(os.getenv("LIVE_STATUS_TTL_SEC", "86400"))


class TelemetryEvent(BaseModel):
    """Canonical event contract accepted from the telemetry topic."""

    vin: str = Field(min_length=17, max_length=17)
    ts: datetime
    seq: int = Field(ge=0)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    speed_kmh: float = Field(ge=0)
    odo_km: float = Field(ge=0)
    ignition_status: bool
    fuel_level_pct: float | None = Field(default=None, ge=0, le=100)
    soc_pct: float | None = Field(default=None, ge=0, le=100)
    dtc: list[str] | None = None
    evt: Literal["HARSH_BRAKE", "HARSH_ACCELERATION", "IDLE_START", "IDLE_END", "TRIP_START", "TRIP_END"] | None = None


INSERT_SQL = """
    INSERT INTO telemetry_events
        (vin, ts, lat, lon, speed_kmh, odo_km, ignition_status,
         fuel_level_pct, soc_pct, dtc, evt, seq)
    VALUES %s
    ON CONFLICT (vin, ts, seq) DO NOTHING
"""


_dlq_producer = None

def get_dlq_producer():
    global _dlq_producer
    if _dlq_producer is None:
        from kafka import KafkaProducer
        _dlq_producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
    return _dlq_producer


def send_to_dlq(record, error_detail: str) -> None:
    """Send a malformed event to the dead-letter topic for later recovery."""
    try:
        dlq_event = {
            "original_topic": record.topic,
            "original_partition": record.partition,
            "original_offset": record.offset,
            "original_value": record.value.decode("utf-8", errors="replace") if isinstance(record.value, bytes) else record.value,
            "error": error_detail,
            "timestamp": datetime.utcnow().isoformat(),
        }
        producer = get_dlq_producer()
        producer.send(DLQ_TOPIC, dlq_event)
        producer.flush()
        logger.info("dlq_sent topic=%s offset=%s", DLQ_TOPIC, record.offset)
    except Exception as dlq_err:
        logger.error("dlq_send_failed offset=%s err=%s", record.offset, dlq_err)


def connect_postgres():
    connection = psycopg2.connect(POSTGRES_URL)
    connection.autocommit = False
    return connection


def create_consumer() -> KafkaConsumer:
    return KafkaConsumer(
        TELEMETRY_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        group_id=CONSUMER_GROUP,
        client_id="telemetry-ingestion",
        max_poll_records=BATCH_SIZE,
    )


def persist_batch(connection, events: list[TelemetryEvent]) -> None:
    rows = [
        (event.vin, event.ts, event.lat, event.lon, event.speed_kmh, event.odo_km,
         event.ignition_status, event.fuel_level_pct, event.soc_pct, event.dtc, event.evt, event.seq)
        for event in events
    ]
    with connection.cursor() as cursor:
        psycopg2.extras.execute_values(cursor, INSERT_SQL, rows, page_size=BATCH_SIZE)
    connection.commit()


def update_live_status(cache: redis.Redis, events: list[TelemetryEvent]) -> None:
    pipeline = cache.pipeline(transaction=False)
    
    # Track the latest event per VIN in this batch to avoid stale overwrites
    latest_events = {}
    for event in events:
        if event.vin not in latest_events or event.ts > latest_events[event.vin].ts:
            latest_events[event.vin] = event

    for vin, event in latest_events.items():
        key = f"vehicle:{vin}:status"
        current_ts_str = cache.hget(key, "last_seen")
        if current_ts_str:
            try:
                current_ts = datetime.fromisoformat(current_ts_str.decode('utf-8') if isinstance(current_ts_str, bytes) else current_ts_str)
                if event.ts <= current_ts:
                    continue
            except (ValueError, AttributeError):
                pass
        pipeline.hset(key, mapping={
            "lat": event.lat,
            "lon": event.lon,
            "speed_kmh": event.speed_kmh,
            "ignition_status": str(event.ignition_status).lower(),
            "last_seen": event.ts.isoformat(),
            "sequence": event.seq,
        })
        pipeline.expire(key, LIVE_STATUS_TTL_SEC)
    pipeline.execute()


def log_consumer_lag(consumer: KafkaConsumer) -> None:
    assignments = consumer.assignment()
    if not assignments:
        return
    end_offsets = consumer.end_offsets(assignments)
    lag = sum(max(0, end_offsets[partition] - consumer.position(partition)) for partition in assignments)
    logger.info("consumer_lag topic=%s partitions=%s messages=%s", TELEMETRY_TOPIC, len(assignments), lag)


def run() -> None:
    cache = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True,
                        socket_connect_timeout=3, socket_timeout=3, health_check_interval=30)
    consumer = create_consumer()
    connection = connect_postgres()
    last_lag_log = 0.0
    logger.info("consumer_started topic=%s group=%s batch_size=%s", TELEMETRY_TOPIC, CONSUMER_GROUP, BATCH_SIZE)

    try:
        while True:
            polled = consumer.poll(timeout_ms=POLL_TIMEOUT_MS, max_records=BATCH_SIZE)
            records = [record for partition_records in polled.values() for record in partition_records]
            if not records:
                continue

            valid_events: list[TelemetryEvent] = []
            for record in records:
                try:
                    payload = json.loads(record.value.decode("utf-8"))
                    valid_events.append(TelemetryEvent.model_validate(payload))
                except json.JSONDecodeError as error:
                    logger.warning("invalid_json topic=%s partition=%s offset=%s error=%s",
                                   record.topic, record.partition, record.offset, str(error))
                    send_to_dlq(record, f"JSONDecodeError: {error}")
                except ValidationError as error:
                    logger.warning("invalid_event topic=%s partition=%s offset=%s errors=%s",
                                   record.topic, record.partition, record.offset, error.errors())
                    send_to_dlq(record, str(error.errors()))

            try:
                if valid_events:
                    persist_batch(connection, valid_events)
                    update_live_status(cache, valid_events)
                # Commit only after both durable storage and cache update succeed.
                consumer.commit()
                logger.info("batch_processed received=%s valid=%s", len(records), len(valid_events))
            except (psycopg2.Error, redis.RedisError, KafkaError) as error:
                connection.rollback()
                logger.exception("batch_failed; offsets were not committed: %s", error)
                connection.close()
                time.sleep(2)
                connection = connect_postgres()

            if time.monotonic() - last_lag_log >= 30:
                log_consumer_lag(consumer)
                last_lag_log = time.monotonic()
    finally:
        connection.close()
        consumer.close()


if __name__ == "__main__":
    run()
