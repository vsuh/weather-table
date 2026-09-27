"""FastAPI приложение — REST API + веб-дашборд."""

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Добавляем корень проекта в sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from storage.database import get_session, init_db, sync_sensors
from storage.models import Reading, Sensor
from collector.registry import load_registry
from api.health import (
    STATUS_OK,
    build_report,
)
from api.metrics import render_metrics
from storage.retention import cleanup_old_readings, count_old_readings
from logging_utils import setup_logging

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Weather Table",
    description="API и дашборд для данных датчиков температуры и влажности",
    version="2.0.0",
)

templates = Jinja2Templates(directory="api/templates")


@app.on_event("startup")
def startup():
    setup_logging()
    init_db()
    try:
        sync_sensors(load_registry())
    except Exception:
        logger.exception("Failed to sync sensors on startup")
    logger.info("API server started")


def _serialize_reading(r: Reading) -> dict:
    return {
        "id": r.id,
        "sensor_id": r.sensor_id,
        "source": r.source,
        "temperature": r.temperature,
        "humidity": r.humidity,
        "battery_mv": r.battery_mv,
        "battery": r.battery,
        "packets_count": r.packets_count,
        "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
    }


def _serialize_sensor(s: Sensor) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "location": s.location,
        "source": s.source,
        "mac": s.mac,
        "protocol": s.protocol,
        "active": s.active,
    }


# ---------- Sensors ----------

@app.get("/api/sensors")
def list_sensors(active_only: bool = True):
    """Список датчиков."""
    with get_session() as session:
        q = session.query(Sensor)
        if active_only:
            q = q.filter(Sensor.active.is_(True))
        return [_serialize_sensor(s) for s in q.order_by(Sensor.location).all()]


# ---------- Readings ----------

@app.get("/api/readings")
def list_readings(
    sensor_id: Optional[str] = Query(None, description="Фильтр по датчику"),
    limit: int = Query(100, ge=1, le=10000),
    offset: int = Query(0, ge=0),
):
    """Последние N показаний (опционально по датчику)."""
    with get_session() as session:
        stmt = select(Reading).order_by(Reading.recorded_at.desc())
        if sensor_id:
            stmt = stmt.where(Reading.sensor_id == sensor_id)
        stmt = stmt.limit(limit).offset(offset)
        rows = session.execute(stmt).scalars().all()
        return [_serialize_reading(r) for r in rows]


@app.get("/api/readings/latest")
def latest_reading(
    sensor_id: Optional[str] = Query(None, description="Фильтр по датчику"),
):
    """Самое свежее показание (опционально по датчику)."""
    with get_session() as session:
        q = session.query(Reading)
        if sensor_id:
            q = q.filter(Reading.sensor_id == sensor_id)
        row = q.order_by(Reading.recorded_at.desc()).first()
        if not row:
            return {"error": "No readings found"}
        return _serialize_reading(row)


@app.get("/api/stats/summary")
def stats_summary(
    sensor_id: Optional[str] = Query(None, description="Фильтр по датчику"),
):
    """Сводная статистика min/max/avg (опционально по датчику)."""
    with get_session() as session:
        q = session.query(
            func.min(Reading.temperature),
            func.max(Reading.temperature),
            func.avg(Reading.temperature),
            func.min(Reading.humidity),
            func.max(Reading.humidity),
            func.avg(Reading.humidity),
            func.count(Reading.id),
        )
        if sensor_id:
            q = q.filter(Reading.sensor_id == sensor_id)
        agg = q.first()

        if not agg or agg[6] == 0 or agg[0] is None:
            return {"error": "No readings found"}

        return {
            "sensor_id": sensor_id,
            "count": agg[6],
            "temperature": {
                "min": round(agg[0], 2) if agg[0] is not None else None,
                "max": round(agg[1], 2) if agg[1] is not None else None,
                "avg": round(float(agg[2]), 2) if agg[2] is not None else None,
            },
            "humidity": {
                "min": round(agg[3], 2) if agg[3] is not None else None,
                "max": round(agg[4], 2) if agg[4] is not None else None,
                "avg": round(float(agg[5]), 2) if agg[5] is not None else None,
            },
        }


@app.get("/api/readings/time-series")
def time_series(
    hours: int = Query(24, ge=1, le=720, description="Количество часов назад"),
    sensor_id: Optional[str] = Query(None, description="Фильтр по датчику"),
    all_sensors: bool = Query(False, description="Вернуть серии по всем датчикам"),
):
    """Данные для графика за N часов.

    При all_sensors=true возвращает структуру:
      { sensor_id: {name, timestamps[], temperatures[], humidities[]} }
    Иначе — плоскую серию по sensor_id (или все вместе).
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)

    with get_session() as session:
        if all_sensors:
            sensors = (
                session.query(Sensor)
                .filter(Sensor.active.is_(True))
                .order_by(Sensor.location)
                .all()
            )
            result: dict[str, dict] = {}
            for s in sensors:
                stmt = (
                    select(Reading.recorded_at, Reading.temperature, Reading.humidity)
                    .where(Reading.sensor_id == s.id)
                    .where(Reading.recorded_at >= cutoff)
                    .order_by(Reading.recorded_at)
                )
                rows = session.execute(stmt).all()
                result[s.id] = {
                    "name": s.name,
                    "location": s.location,
                    "source": s.source,
                    "timestamps": [r[0].isoformat() for r in rows],
                    "temperatures": [r[1] for r in rows],
                    "humidities": [r[2] for r in rows],
                }
            return result

        stmt = (
            select(Reading.recorded_at, Reading.temperature, Reading.humidity)
            .where(Reading.recorded_at >= cutoff)
            .order_by(Reading.recorded_at)
        )
        if sensor_id:
            stmt = stmt.where(Reading.sensor_id == sensor_id)
        rows = session.execute(stmt).all()
        return {
            "sensor_id": sensor_id,
            "timestamps": [r[0].isoformat() for r in rows],
            "temperatures": [r[1] for r in rows],
            "humidities": [r[2] for r in rows],
        }


# ---------- Health / monitoring ----------

def _last_reading_times() -> dict[str, Optional[datetime]]:
    """Возвращает {sensor_id: время последнего показания} для всех датчиков."""
    with get_session() as session:
        rows = session.execute(
            select(Reading.sensor_id, func.max(Reading.recorded_at))
            .group_by(Reading.sensor_id)
        ).all()
        return {sid: ts for sid, ts in rows}


def _health_report() -> dict:
    with get_session() as session:
        sensors = session.query(Sensor).all()
    report = build_report(sensors, _last_reading_times())
    return report.as_dict()


@app.get("/health")
def health():
    """Liveness/readiness: жив ли сбор и свежи ли данные датчиков.

    200 — все активные датчики свежие, 503 — есть проблемы (устаревание,
    нет данных). Подходит для systemd/watchdog и внешнего мониторинга.
    """
    payload = _health_report()
    if payload["status"] != STATUS_OK:
        return JSONResponse(status_code=503, content=payload)
    return payload


@app.get("/api/status")
def status():
    """Подробный статус сбора: по каждому датчику + сводка (всегда 200)."""
    return _health_report()


# ---------- Prometheus Metrics ----------

@app.get("/metrics")
def metrics():
    """Prometheus metrics endpoint.

    Returns plaintext metrics in Prometheus exposition format.
    Suitable for scraping by Prometheus/Grafana.
    """
    data, content_type = render_metrics()
    return Response(
        content=data,
        media_type=content_type,
    )


# ---------- Retention / cleanup ----------

@app.post("/api/cleanup")
def api_cleanup(days: int = Query(30, ge=1, le=3650)):
    """Удалить старые показания (POST).

    Args:
        days: удалить показания старше этого количества дней.

    Returns:
        { deleted: N, total_old: M }
    """
    total_old = count_old_readings(days)
    deleted = cleanup_old_readings(days)
    return {"days": days, "total_old": total_old, "deleted": deleted}


# ---------- Web Dashboard ----------
@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Веб-дашборд с графиками."""
    return templates.TemplateResponse("dashboard.html", {"request": {}})
