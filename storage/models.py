"""Модели SQLAlchemy для хранения датчиков и показаний."""

from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, Float, Integer, String, Boolean, Index, ForeignKey,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Sensor(Base):
    """Описание датчика (синхронизируется из sensors.yaml)."""

    __tablename__ = "sensors"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    location = Column(String(64), nullable=False)
    source = Column(String(16), nullable=False)  # 'ble' | 'weather'
    mac = Column(String(17), nullable=True)
    protocol = Column(String(16), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    readings = relationship("Reading", back_populates="sensor")

    def __repr__(self):
        return f"<Sensor {self.id} ({self.location}, {self.source})>"


class Reading(Base):
    """Свёртное показание датчика (усреднённое за окно)."""

    __tablename__ = "readings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sensor_id = Column(
        String(64), ForeignKey("sensors.id"), nullable=False, index=True
    )
    source = Column(String(16), nullable=False)  # денормализация для запросов
    temperature = Column(Float, nullable=True)
    humidity = Column(Float, nullable=True)
    battery_mv = Column(Integer, nullable=True)
    battery = Column(Integer, nullable=True)
    packets_count = Column(Integer, default=1, nullable=False)
    recorded_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    sensor = relationship("Sensor", back_populates="readings")

    __table_args__ = (
        Index("idx_sensor_time", "sensor_id", "recorded_at"),
    )

    def __repr__(self):
        return (
            f"<Reading {self.sensor_id} temp={self.temperature} "
            f"hum={self.humidity} time={self.recorded_at}>"
        )
