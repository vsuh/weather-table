"""Реестр датчиков: загрузка описаний из sensors.yaml."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

import config

logger = logging.getLogger(__name__)


@dataclass
class SensorConfig:
    """Описание одного датчика."""
    id: str
    name: str
    location: str
    source: str  # 'ble' | 'weather'
    mac: Optional[str] = None
    protocol: str = "atc"  # 'atc' | 'bthome' (только для ble)


@dataclass
class SensorRegistry:
    """Реестр всех датчиков."""
    sensors: list[SensorConfig] = field(default_factory=list)

    @property
    def ble_sensors(self) -> list[SensorConfig]:
        return [s for s in self.sensors if s.source == "ble"]

    @property
    def weather_sensors(self) -> list[SensorConfig]:
        return [s for s in self.sensors if s.source == "weather"]

    def by_mac(self) -> dict[str, SensorConfig]:
        """MAC (upper) -> SensorConfig."""
        return {s.mac.upper(): s for s in self.ble_sensors if s.mac}

    def by_id(self, sensor_id: str) -> Optional[SensorConfig]:
        for s in self.sensors:
            if s.id == sensor_id:
                return s
        return None


def load_registry(path: Path | None = None) -> SensorRegistry:
    """Загружает список датчиков из sensors.yaml."""
    path = path or config.SENSORS_FILE

    if not path.exists():
        logger.error("Sensors file not found: %s", path)
        return SensorRegistry()

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    items = raw.get("sensors", [])
    sensors: list[SensorConfig] = []

    for item in items:
        try:
            sensor = SensorConfig(
                id=item["id"],
                name=item.get("name", item["id"]),
                location=item.get("location", item["id"]),
                source=item["source"],
                mac=item.get("mac"),
                protocol=item.get("protocol", "atc"),
            )
        except KeyError as e:
            logger.error("Sensor entry missing required key %s: %s", e, item)
            continue

        if sensor.source == "ble" and not sensor.mac:
            logger.error("BLE sensor %s has no mac, skipped", sensor.id)
            continue

        sensors.append(sensor)

    logger.info(
        "Loaded %d sensors (%d BLE, %d weather)",
        len(sensors), len([s for s in sensors if s.source == "ble"]),
        len([s for s in sensors if s.source == "weather"]),
    )
    return SensorRegistry(sensors=sensors)
