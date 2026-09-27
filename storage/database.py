"""Инициализация и управление SQLite-базой данных."""

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import config
from storage.models import Base, Sensor

logger = logging.getLogger(__name__)


_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        config.DB_DIR.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{config.DB_PATH}",
            connect_args={"check_same_thread": False},
        )
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine())
    return _session_factory


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Контекстный менеджер для получения сессии БД."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Создаёт таблицы, если они не существуют."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    logger.info("Database initialised: %s", config.DB_PATH)


def sync_sensors(registry) -> None:
    """Синхронизирует таблицу sensors с реестром из sensors.yaml."""
    from collector.registry import SensorRegistry  # избегаем циклического импорта

    with get_session() as session:
        known_ids = {s.id for s in session.query(Sensor).all()}

        for sc in registry.sensors:
            sensor = session.get(Sensor, sc.id)
            if sensor is None:
                sensor = Sensor(
                    id=sc.id, name=sc.name, location=sc.location,
                    source=sc.source, mac=sc.mac, protocol=sc.protocol,
                    active=True,
                )
                session.add(sensor)
            else:
                sensor.name = sc.name
                sensor.location = sc.location
                sensor.source = sc.source
                sensor.mac = sc.mac
                sensor.protocol = sc.protocol
                sensor.active = True

        # Деактивируем датчики, которых больше нет в конфиге
        configured = {sc.id for sc in registry.sensors}
        for sensor_id in known_ids - configured:
            sensor = session.get(Sensor, sensor_id)
            if sensor:
                sensor.active = False

    logger.info("Sensors synced: %d active", len(registry.sensors))
