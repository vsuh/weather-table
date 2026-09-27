"""Агрегатор данных датчиков (мульти-датчиковый).

Алгоритм для BLE-датчиков:
  1. BLE-сканер вызывает callback на каждый advertisement датчика.
  2. Датчик шлёт один и тот же пакет несколько раз (re-broadcast)
     с одинаковым counter — это дубликаты одного измерения.
  3. Уникальные измерения (по counter) копятся в окне датчика.
  4. По истечении окна измерения сворачиваются в средние значения
     и пишутся одной записью в БД.
  5. Окно сбрасывается.

Для погодных датчиков (source=weather):
  - Раз в WEATHER_POLL_SECONDS берём почасовые данные Open-Meteo
    и пишем каждое часовое значение отдельной записью (upsert по времени).
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from storage.database import get_session
from storage.models import Reading
from collector.parser import SensorReading, parse_atc_custom, parse_bthome_v2
from collector.registry import SensorRegistry, SensorConfig
from collector.ble_reader import run_scanner
from collector import weather

import config
from api.metrics import (
    aggregation_packets,
    aggregation_duplicates,
    readings_total,
)

logger = logging.getLogger(__name__)


@dataclass
class Measurement:
    """Одно уникальное измерение (уникальный counter)."""
    counter: int
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    battery_mv: Optional[int] = None
    battery: Optional[int] = None
    rssi: Optional[int] = None
    first_seen: float = 0.0
    last_seen: float = 0.0


class SensorAggregator:
    """Накапливает уникальные измерения одного датчика и сворачивает их."""

    def __init__(self, sensor: SensorConfig, window_seconds: int = 60):
        self.sensor = sensor
        self.window_seconds = window_seconds
        self._measurements: dict[int, Measurement] = {}
        self._window_start: Optional[float] = None
        self._total_packets = 0
        self._total_duplicates = 0

    def add_packet(self, reading: SensorReading, rssi: int) -> str:
        """Добавляет пакет. Returns 'new' | 'duplicate'."""
        now = asyncio.get_event_loop().time()
        counter = reading.counter

        if counter is None:
            counter = self._total_packets

        self._total_packets += 1
        aggregation_packets.inc()

        if counter in self._measurements:
            self._measurements[counter].last_seen = now
            self._total_duplicates += 1
            aggregation_duplicates.inc()
            return "duplicate"

        if self._window_start is None:
            self._window_start = now

        self._measurements[counter] = Measurement(
            counter=counter,
            temperature=reading.temperature,
            humidity=reading.humidity,
            battery_mv=reading.battery_mv,
            battery=reading.battery,
            rssi=rssi,
            first_seen=now,
            last_seen=now,
        )
        return "new"

    def should_flush(self) -> bool:
        if self._window_start is None:
            return False
        return (asyncio.get_event_loop().time() - self._window_start) >= self.window_seconds

    def flush(self) -> Optional[Reading]:
        """Сворачивает измерения окна в одну запись БД."""
        if not self._measurements:
            self._window_start = None
            return None

        ms = list(self._measurements.values())
        n = len(ms)

        temps = [m.temperature for m in ms if m.temperature is not None]
        hums = [m.humidity for m in ms if m.humidity is not None]
        bats_mv = [m.battery_mv for m in ms if m.battery_mv is not None]
        bats_pct = [m.battery for m in ms if m.battery is not None]

        avg_temp = sum(temps) / len(temps) if temps else None
        avg_hum = sum(hums) / len(hums) if hums else None
        avg_bat_mv = int(sum(bats_mv) / len(bats_mv)) if bats_mv else None
        avg_bat_pct = int(sum(bats_pct) / len(bats_pct)) if bats_pct else None

        with get_session() as session:
            db_reading = Reading(
                sensor_id=self.sensor.id,
                source=self.sensor.source,
                temperature=round(avg_temp, 2) if avg_temp is not None else None,
                humidity=round(avg_hum, 2) if avg_hum is not None else None,
                battery_mv=avg_bat_mv,
                battery=avg_bat_pct,
                packets_count=n,
                recorded_at=datetime.now(timezone.utc),
            )
            session.add(db_reading)
            session.flush()
            db_id = db_reading.id

        readings_total.labels(
            sensor_id=self.sensor.id, source=self.sensor.source
        ).inc()

        logger.info(
            "[%s] Saved #%d: T=%.2f°C RH=%.2f%% BAT=%dmV(%d%%) from %d measurements",
            self.sensor.id, db_id,
            avg_temp or 0, avg_hum or 0, avg_bat_mv or 0, avg_bat_pct or 0, n,
        )

        self._measurements.clear()
        self._window_start = None
        self._total_packets = 0
        self._total_duplicates = 0
        return db_reading


class AggregatorManager:
    """Управляет агрегаторами всех BLE-датчиков."""

    def __init__(self, registry: SensorRegistry, window_seconds: int):
        self.window_seconds = window_seconds
        self.aggregators: dict[str, SensorAggregator] = {
            s.id: SensorAggregator(s, window_seconds)
            for s in registry.ble_sensors
        }

    def add_packet(self, sensor: SensorConfig, reading: SensorReading, rssi: int) -> str:
        agg = self.aggregators.get(sensor.id)
        if agg is None:
            return "unknown_sensor"
        return agg.add_packet(reading, rssi)

    def flush_due(self) -> None:
        for agg in self.aggregators.values():
            if agg.should_flush():
                agg.flush()

    def flush_all(self) -> None:
        for agg in self.aggregators.values():
            agg.flush()


def _parse_payload(protocol: str, service_uuid: str, raw_data: bytes) -> Optional[SensorReading]:
    """Выбирает парсер по протоколу датчика (или UUID как fallback)."""
    uuid = service_uuid.lower()
    if protocol == "atc" or "181a" in uuid:
        return parse_atc_custom(raw_data)
    if protocol == "bthome" or "181c" in uuid:
        return parse_bthome_v2(raw_data)
    return None


# ============================================================
# Weather ingestion
# ============================================================

def ingest_weather(sensor: SensorConfig) -> int:
    """Записывает почасовые данные Open-Meteo как показания датчика.

    Дедупликация: пропускаем часы, для которых уже есть запись.

    Returns:
        Количество новых записей.
    """
    records = weather.fetch_hourly_weather()
    if not records:
        return 0

    written = 0
    with get_session() as session:
        existing = {
            r[0] for r in session.execute(
                select(Reading.recorded_at).where(Reading.sensor_id == sensor.id)
            ).all()
        }

        for rec in records:
            ts = rec["time"]
            if ts is None or ts in existing:
                continue
            session.add(Reading(
                sensor_id=sensor.id,
                source="weather",
                temperature=rec["temperature"],
                humidity=rec["humidity"],
                packets_count=1,
                recorded_at=ts,
            ))
            written += 1
            readings_total.labels(
                sensor_id=sensor.id, source="weather"
            ).inc()

    if written:
        logger.info("[%s] Weather: wrote %d new hourly records", sensor.id, written)
    return written


async def _weather_loop(registry: SensorRegistry) -> None:
    """Периодически подтягивает уличную погоду."""
    weather_sensors = registry.weather_sensors
    if not weather_sensors:
        return

    while True:
        for sensor in weather_sensors:
            try:
                ingest_weather(sensor)
            except Exception:
                logger.exception("[%s] Weather ingest failed", sensor.id)
        await asyncio.sleep(config.WEATHER_POLL_SECONDS)


async def _flush_loop(manager: AggregatorManager) -> None:
    """Периодически закрывает окна агрегации."""
    while True:
        await asyncio.sleep(5)
        manager.flush_due()


async def run_collector(registry: SensorRegistry) -> None:
    """Запускает сбор: BLE-скан + погодный опрос + флаш окон."""
    manager = AggregatorManager(registry, config.AGGREGATION_WINDOW_SECONDS)

    logger.info(
        "Collector started. Window=%ds, BLE sensors=%d, weather sensors=%d",
        config.AGGREGATION_WINDOW_SECONDS,
        len(registry.ble_sensors), len(registry.weather_sensors),
    )

    def on_packet(sensor: SensorConfig, raw_data: bytes, rssi: int, service_uuid: str):
        reading = _parse_payload(sensor.protocol, service_uuid, raw_data)
        if reading is None:
            logger.debug("[%s] Failed to parse packet (uuid=%s)", sensor.id, service_uuid)
            return
        status = manager.add_packet(sensor, reading, rssi)
        logger.debug(
            "[%s] counter=%s status=%s T=%.2f RH=%.2f",
            sensor.id, reading.counter, status,
            reading.temperature or 0, reading.humidity or 0,
        )

    flusher = asyncio.create_task(_flush_loop(manager))
    weather_task = asyncio.create_task(_weather_loop(registry))

    try:
        if registry.ble_sensors:
            await run_scanner(registry, on_packet)
        else:
            # Только погодные датчики — держим процесс живым
            await asyncio.gather(weather_task)
    except asyncio.CancelledError:
        logger.info("Collector cancelled, flushing remaining data...")
        manager.flush_all()
        raise
    finally:
        flusher.cancel()
        weather_task.cancel()
