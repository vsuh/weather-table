"""Получение почасовой уличной погоды от WeatherAPI.com.

WeatherAPI.com — бесплатный план: 1000 запросов/день.
API: https://api.weatherapi.com/v1/forecast.json?key=KEY&q=LAT,LON&hours=N

Время от API — в локальном часовом поясе локации (tz_id из location).
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)


def _parse_local_time(time_str: str, tz_offset_hours: float) -> datetime:
    """Парсит время от WeatherAPI и конвертирует в UTC.

    WeatherAPI возвращает время в часовом поясе локации (tz_id).
    Мы используем tz_offset_hours из location для конвертации в UTC.
    """
    dt = datetime.fromisoformat(time_str)
    # Сдвигаем обратно к UTC
    dt_utc = dt - timedelta(hours=tz_offset_hours)
    return dt_utc.replace(tzinfo=timezone.utc)


def fetch_hourly_weather(
    lat: float | None = None,
    lon: float | None = None,
) -> list[dict]:
    """Возвращает почасовые значения погоды.

    Returns:
        Список dict: {'time': datetime (UTC), 'temperature': float, 'humidity': float}.
        Пустой список при ошибке.
    """
    if not config.WEATHER_API_KEY:
        logger.warning("WEATHER_API_KEY is not set, skipping weather fetch")
        return []

    lat = config.WEATHER_LAT if lat is None else lat
    lon = config.WEATHER_LON if lon is None else lon

    params = {
        "key": config.WEATHER_API_KEY,
        "q": f"{lat},{lon}",
        "hours": 72,  # 72 часа прогноза — максимум на free tier
    }

    try:
        resp = requests.get(config.WEATHER_API_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("WeatherAPI.com request failed: %s", e)
        return []

    # Проверка на ошибку от API (неверный ключ и т.д.)
    error = data.get("error")
    if error:
        logger.error("WeatherAPI.com error: %s", error.get("message"))
        return []

    # Извлекаем часовой пояс локации
    location = data.get("location", {})
    tz_offset = location.get("tz_id", "UTC")
    # Определяем смещение UTC для Moscow = +3, London = 0 и т.д.
    tz_offsets = {
        "Europe/Moscow": 3,
        "Europe/London": 0,
        "Europe/Berlin": 1,
        "UTC": 0,
    }
    offset_hours = tz_offsets.get(tz_offset, 0)

    forecastdays = data.get("forecast", {}).get("forecastday", [])
    if not forecastdays:
        logger.warning("WeatherAPI.com returned no forecast data")
        return []

    result: list[dict] = []
    for day in forecastdays:
        for hour_entry in day.get("hour", []):
            time_str = hour_entry.get("time")
            if not time_str:
                continue
            try:
                dt = _parse_local_time(time_str, offset_hours)
            except ValueError:
                continue
            result.append({
                "time": dt,
                "temperature": hour_entry.get("temp_c"),
                "humidity": hour_entry.get("humidity"),
            })

    logger.info(
        "WeatherAPI.com: fetched %d hourly records (tz=%s, offset=%dh)",
        len(result), tz_offset, offset_hours,
    )
    return result


def fetch_current_weather(
    lat: float | None = None,
    lon: float | None = None,
) -> Optional[dict]:
    """Возвращает текущую погоду одним значением."""
    if not config.WEATHER_API_KEY:
        return None

    lat = config.WEATHER_LAT if lat is None else lat
    lon = config.WEATHER_LON if lon is None else lon

    params = {
        "key": config.WEATHER_API_KEY,
        "q": f"{lat},{lon}",
    }

    try:
        resp = requests.get("http://api.weatherapi.com/v1/current.json",
                            params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("WeatherAPI.com current request failed: %s", e)
        return None

    error = data.get("error")
    if error:
        logger.error("WeatherAPI.com error: %s", error.get("message"))
        return None

    current = data.get("current", {})
    location = data.get("location", {})
    time_str = current.get("last_updated")

    try:
        dt = datetime.fromisoformat(time_str).replace(tzinfo=timezone.utc) if time_str else None
    except ValueError:
        dt = None

    return {
        "time": dt,
        "temperature": current.get("temp_c"),
        "humidity": current.get("humidity"),
        "location": location.get("name"),
    }
