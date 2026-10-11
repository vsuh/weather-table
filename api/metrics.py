"""Prometheus-метрики для Grafana.

Эндпоинт /metrics (процесс API) собирает метрики из БД при каждом запросе:
  - weather_temperature_celsius    — последняя температура по датчику
  - weather_humidity_percent       — последняя влажность по датчику
  - weather_battery_percent        — заряд батареи BLE-датчика (%)
  - weather_battery_millivolts     — напряжение батареи BLE-датчика (мВ)
  - weather_readings_latest_age_s  — возраст последнего показания (сек)
  - weather_readings_last_hour     — записей за последний час
  - weather_readings_count         — всего записей в БД по датчику
  - weather_sensors_total          — число активных датчиков (по source)
  - weather_db_up                  — 1, если БД доступна

Записи из будущего (recorded_at > now) игнорируются.

Счётчики коллектора (weather_readings_total, weather_aggregation_packets,
weather_aggregation_duplicates) увеличиваются в процессе коллектора и в /metrics
API не попадают: у коллектора свой реестр `collector_registry`. Пока они нигде
не публикуются (процессы коллектора и API разные).
"""

import logging
from datetime import datetime, timedelta, timezone

from prometheus_client import (
    CollectorRegistry,
    Counter,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import func, select

from storage.database import get_session
from storage.models import Reading, Sensor

logger = logging.getLogger(__name__)

# ---------- Счётчики процесса-коллектора ----------

collector_registry = CollectorRegistry()

readings_total = Counter(
    "weather_readings_total",
    "Readings written by the collector process, labelled by sensor_id and source",
    labelnames=["sensor_id", "source"],
    registry=collector_registry,
)

aggregation_packets = Counter(
    "weather_aggregation_packets",
    "Total BLE packets received by the collector",
    registry=collector_registry,
)

aggregation_duplicates = Counter(
    "weather_aggregation_duplicates",
    "Total duplicate packets dropped by dedup",
    registry=collector_registry,
)


# ---------- Метрики из БД (процесс API) ----------

registry = CollectorRegistry()


class DbCollector:
    """Собирает метрики из БД в момент запроса /metrics."""

    def collect(self):
        db_up = GaugeMetricFamily("weather_db_up", "1 if the database is reachable")
        sensors_total = GaugeMetricFamily(
            "weather_sensors_total", "Number of active sensors", labels=["source"]
        )
        temperature = GaugeMetricFamily(
            "weather_temperature_celsius", "Latest temperature",
            labels=["sensor_id", "source", "location"],
        )
        humidity = GaugeMetricFamily(
            "weather_humidity_percent", "Latest relative humidity",
            labels=["sensor_id", "source", "location"],
        )
        battery = GaugeMetricFamily(
            "weather_battery_percent", "Latest battery level of BLE sensor",
            labels=["sensor_id", "source"],
        )
        battery_mv = GaugeMetricFamily(
            "weather_battery_millivolts", "Latest battery voltage of BLE sensor",
            labels=["sensor_id", "source"],
        )
        age = GaugeMetricFamily(
            "weather_readings_latest_age_s", "Age of the latest reading (seconds)",
            labels=["sensor_id", "source"],
        )
        last_hour = GaugeMetricFamily(
            "weather_readings_last_hour", "Readings written during the last hour",
            labels=["sensor_id", "source"],
        )
        count = GaugeMetricFamily(
            "weather_readings_count", "Readings stored in the database",
            labels=["sensor_id", "source"],
        )

        try:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            hour_ago = now - timedelta(hours=1)

            with get_session() as session:
                sensors = session.query(Sensor).filter(Sensor.active.is_(True)).all()

                latest_ts = dict(session.execute(
                    select(Reading.sensor_id, func.max(Reading.recorded_at))
                    .where(Reading.recorded_at <= now)
                    .group_by(Reading.sensor_id)
                ).all())
                counts = dict(session.execute(
                    select(Reading.sensor_id, func.count(Reading.id))
                    .group_by(Reading.sensor_id)
                ).all())
                recent = dict(session.execute(
                    select(Reading.sensor_id, func.count(Reading.id))
                    .where(Reading.recorded_at > hour_ago)
                    .where(Reading.recorded_at <= now)
                    .group_by(Reading.sensor_id)
                ).all())

                by_source: dict[str, int] = {}
                for s in sensors:
                    by_source[s.source] = by_source.get(s.source, 0) + 1
                    base = [s.id, s.source]

                    count.add_metric(base, counts.get(s.id, 0))
                    last_hour.add_metric(base, recent.get(s.id, 0))

                    ts = latest_ts.get(s.id)
                    if ts is None:
                        continue
                    age.add_metric(base, (now - ts).total_seconds())

                    row = session.execute(
                        select(Reading)
                        .where(Reading.sensor_id == s.id, Reading.recorded_at == ts)
                        .limit(1)
                    ).scalars().first()
                    if row is None:
                        continue
                    if row.temperature is not None:
                        temperature.add_metric(base + [s.location], row.temperature)
                    if row.humidity is not None:
                        humidity.add_metric(base + [s.location], row.humidity)
                    if row.battery is not None:
                        battery.add_metric(base, row.battery)
                    if row.battery_mv is not None:
                        battery_mv.add_metric(base, row.battery_mv)

            for source, n in by_source.items():
                sensors_total.add_metric([source], n)
            db_up.add_metric([], 1)
        except Exception:
            logger.exception("Failed to collect metrics from DB")
            db_up.add_metric([], 0)

        yield db_up
        yield sensors_total
        yield temperature
        yield humidity
        yield battery
        yield battery_mv
        yield age
        yield last_hour
        yield count


registry.register(DbCollector())


def render_metrics() -> tuple[bytes, str]:
    """Возвращает (payload, content_type) для /metrics."""
    return generate_latest(registry), CONTENT_TYPE_LATEST
