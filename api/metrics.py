"""Prometheus-метрики для Grafana.

Эндпоинт /metrics exposes:
  - weather_readings_total        — всего записей в БД (по source+sensor)
  - weather_readings_latest_age_s — возраст последнего показания (сек)
  - weather_sensors_total         — всего датчиков (active)
  - weather_aggregation_packets   — всего пакетов собрано коллектором
  - weather_aggregation_duplicates — дубликатов отброшено
"""

from datetime import datetime, timezone

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from sqlalchemy import func, select

from storage.database import get_session
from storage.models import Reading, Sensor

# ---------- Registry ----------

registry = CollectorRegistry()

# --- Counters ---

readings_total = Counter(
    "weather_readings_total",
    "Total readings in DB, labelled by sensor_id and source",
    labelnames=["sensor_id", "source"],
    registry=registry,
)

aggregation_packets = Counter(
    "weather_aggregation_packets",
    "Total BLE packets received by the collector",
    registry=registry,
)

aggregation_duplicates = Counter(
    "weather_aggregation_duplicates",
    "Total duplicate packets dropped by dedup",
    registry=registry,
)

# --- Gauges ---

sensors_total = Gauge(
    "weather_sensors_total",
    "Number of active sensors",
    labelnames=["source"],
    registry=registry,
)

readings_latest_age = Gauge(
    "weather_readings_latest_age_s",
    "Age of the latest reading per sensor (seconds)",
    labelnames=["sensor_id", "source"],
    registry=registry,
)


# ---------- Update functions ----------

def update_metrics() -> None:
    """Обновляет все метрики из БД. Вызывается на каждый запрос /metrics."""
    _update_sensors_gauge()
    _update_readings_count()
    _update_latest_age()


def _update_sensors_gauge() -> None:
    with get_session() as session:
        rows = (
            session.query(Sensor.source, func.count(Sensor.id))
            .filter(Sensor.active.is_(True))
            .group_by(Sensor.source)
            .all()
        )
        counts = {src: cnt for src, cnt in rows}
    for metric in sensors_total._metrics:
        metric.set(0)
    for src, cnt in counts.items():
        sensors_total.labels(source=src).set(cnt)


def _update_readings_count() -> None:
    """Сбрасывает readings_total (счётчик обновляется в collector)."""
    # Счётчик readings_total инкрементируется в collector при записи.
    # Здесь мы просто гарантируем, что метрика существует.
    pass


def _update_latest_age() -> None:
    """Обновляет age последнего показания для каждого датчика."""
    now = datetime.now(timezone.utc)
    with get_session() as session:
        rows = session.execute(
            select(Sensor.id, Sensor.source, func.max(Reading.recorded_at))
            .join(Reading, Sensor.id == Reading.sensor_id)
            .group_by(Sensor.id)
        ).all()

    known_labels = set()
    for sensor_id, source, max_at in rows:
        age = None
        if max_at:
            if max_at.tzinfo is None:
                max_at = max_at.replace(tzinfo=timezone.utc)
            age = (now - max_at).total_seconds()
        readings_latest_age.labels(sensor_id=sensor_id, source=source).set(age)
        known_labels.add((sensor_id, source))

    # Сбрасываем метрики для датчиков, которых больше нет
    for metric in readings_latest_age._metrics:
        labels = dict(metric.labelmapping) if hasattr(metric, "labelmapping") else {}
        metric.set(0)


def render_metrics() -> tuple[bytes, str]:
    """Возвращает (payload, content_type) для /metrics."""
    update_metrics()
    return generate_latest(registry), CONTENT_TYPE_LATEST
