"""Получение почасовой уличной погоды от Open-Meteo.

Open-Meteo — бесплатный API без ключа: https://open-meteo.com/
Запрашиваем почасовые temperature_2m и relative_humidity_2m.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)


def fetch_hourly_weather(
    lat: float | None = None,
    lon: float | None = None,
) -> list[dict]:
    """Возвращает почасовые значения погоды.

    Returns:
        Список dict: {'time': datetime (UTC), 'temperature': float, 'humidity': float}.
        Пустой список при ошибке.
    """
    lat = config.WEATHER_LAT if lat is None else lat
    lon = config.WEATHER_LON if lon is None else lon

    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,relative_humidity_2m",
        "timezone": "UTC",
        "past_days": 1,
        "forecast_days": 2,
    }

    try:
        resp = requests.get(config.WEATHER_API_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("Open-Meteo request failed: %s", e)
        return []

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    hums = hourly.get("relative_humidity_2m", [])

    result: list[dict] = []
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        result.append({
            "time": dt,
            "temperature": temps[i] if i < len(temps) else None,
            "humidity": hums[i] if i < len(hums) else None,
        })

    logger.info("Open-Meteo: fetched %d hourly records", len(result))
    return result


def fetch_current_weather(
    lat: float | None = None,
    lon: float | None = None,
) -> Optional[dict]:
    """Возвращает текущую погоду одним значением."""
    lat = config.WEATHER_LAT if lat is None else lat
    lon = config.WEATHER_LON if lon is None else lon

    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m",
        "timezone": "UTC",
    }

    try:
        resp = requests.get(config.WEATHER_API_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("Open-Meteo request failed: %s", e)
        return None

    current = data.get("current", {})
    t = current.get("time")
    try:
        dt = datetime.fromisoformat(t).replace(tzinfo=timezone.utc) if t else None
    except ValueError:
        dt = None

    return {
        "time": dt,
        "temperature": current.get("temperature_2m"),
        "humidity": current.get("relative_humidity_2m"),
    }
