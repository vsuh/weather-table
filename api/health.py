"""Оценка здоровья системы: свежесть данных по датчикам.

Используется эндпоинтами /health и /api/status.

Ключевая идея: система жива, если каждый активный датчик пишет свежие данные.
Порог «устаревания» зависит от источника:
  - BLE     → config.HEALTH_BLE_STALE_SECONDS
  - weather → config.HEALTH_WEATHER_STALE_SECONDS

Логика отделена от БД (чистая функция evaluate_sensor), чтобы её можно было
покрыть тестами без SQLite.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import config


# Статусы (по возрастанию серьёзности).
STATUS_OK = "ok"
STATUS_STALE = "stale"
STATUS_NO_DATA = "no_data"
STATUS_INACTIVE = "inactive"

# Серьёзность для агрегации: чем больше, тем хуже.
_SEVERITY = {
    STATUS_OK: 0,
    STATUS_INACTIVE: 1,
    STATUS_STALE: 2,
    STATUS_NO_DATA: 3,
}


def stale_threshold(source: str) -> int:
    """Порог устаревания (сек) для источника датчика."""
    if source == "weather":
        return config.HEALTH_WEATHER_STALE_SECONDS
    return config.HEALTH_BLE_STALE_SECONDS


@dataclass
class SensorHealth:
    """Здоровье одного датчика."""
    sensor_id: str
    name: str
    source: str
    status: str
    last_reading_at: Optional[datetime] = None
    age_seconds: Optional[float] = None
    threshold_seconds: float = 0.0

    def as_dict(self) -> dict:
        return {
            "sensor_id": self.sensor_id,
            "name": self.name,
            "source": self.source,
            "status": self.status,
            "last_reading_at": (
                self.last_reading_at.isoformat() if self.last_reading_at else None
            ),
            "age_seconds": (
                round(self.age_seconds, 1) if self.age_seconds is not None else None
            ),
            "threshold_seconds": self.threshold_seconds,
        }


@dataclass
class HealthReport:
    """Сводный отчёт о здоровье системы."""
    status: str
    sensors: list[SensorHealth] = field(default_factory=list)
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "checked_at": self.checked_at.isoformat(),
            "sensors": [s.as_dict() for s in self.sensors],
        }


def evaluate_sensor(
    sensor_id: str,
    name: str,
    source: str,
    active: bool,
    last_reading_at: Optional[datetime],
    now: Optional[datetime] = None,
) -> SensorHealth:
    """Оценивает здоровье одного датчика (чистая функция).

    Args:
        active: датчик активен в конфиге.
        last_reading_at: время последнего показания (UTC, наивный или aware).
        now: текущее время (для тестов). По умолчанию — сейчас UTC.
    """
    now = now or datetime.now(timezone.utc)

    # Приводим обе метки к aware-UTC для корректного вычитания.
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if last_reading_at is not None and last_reading_at.tzinfo is None:
        last_reading_at = last_reading_at.replace(tzinfo=timezone.utc)

    threshold = stale_threshold(source)

    if not active:
        status = STATUS_INACTIVE
        age = None
    elif last_reading_at is None:
        status = STATUS_NO_DATA
        age = None
    else:
        age = (now - last_reading_at).total_seconds()
        status = STATUS_OK if age <= threshold else STATUS_STALE

    return SensorHealth(
        sensor_id=sensor_id,
        name=name,
        source=source,
        status=status,
        last_reading_at=last_reading_at,
        age_seconds=age,
        threshold_seconds=threshold,
    )


def overall_status(sensors: list[SensorHealth]) -> str:
    """Агрегирует статус по всем датчикам: берём наихудший.

    Если активных датчиков нет — общий статус 'inactive'.
    Пустой список (нет датчиков в конфиге) — 'no_data'.
    """
    if not sensors:
        return STATUS_NO_DATA
    return max(sensors, key=lambda s: _SEVERITY.get(s.status, 0)).status


def build_report(
    sensors,
    last_readings: dict[str, Optional[datetime]],
    now: Optional[datetime] = None,
) -> HealthReport:
    """Строит HealthReport из описаний датчиков и времён последних показаний.

    Args:
        sensors: список объектов с полями id, name, source, active.
        last_readings: {sensor_id: datetime | None}.

    Возвращает отчёт, где общий status='ok' только если все активные
    датчики свежие.
    """
    results = [
        evaluate_sensor(
            sensor_id=s.id,
            name=s.name,
            source=s.source,
            active=bool(s.active),
            last_reading_at=last_readings.get(s.id),
            now=now,
        )
        for s in sensors
    ]

    active = [r for r in results if r.status != STATUS_INACTIVE]
    if not results:
        overall = STATUS_NO_DATA
    elif not active:
        overall = STATUS_INACTIVE
    else:
        overall = overall_status(active)

    return HealthReport(
        status=overall,
        sensors=results,
        checked_at=now or datetime.now(timezone.utc),
    )
