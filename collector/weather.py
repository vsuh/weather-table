"""Получение уличной погоды (только наблюдённые значения).

Провайдеры (основной задаёт WEATHER_PROVIDER, запасные идут в порядке _PROVIDERS):
  - wttr       : wttr.in в компактном формате, снимок текущего часа;
  - met-norway : MET Norway (api.met.no), снимок текущего часа;
  - open-meteo : Open-Meteo, почасовая история за WEATHER_PAST_HOURS;
  - weatherapi : WeatherAPI.com (только если задан WEATHER_API_KEY).

В БД попадают только часы, которые уже наступили (time <= now).
Прогноз на будущие часы отбрасывается: уличный датчик — это факт, а не прогноз.
Значения MET Norway / Open-Meteo / wttr.in — модельные (не показания станции),
но для текущего и прошедших часов близки к фактической погоде.

Все времена возвращаются в UTC (aware datetime).
"""

import logging
import re
from datetime import datetime, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

import config

logger = logging.getLogger(__name__)


# ============================================================
# HTTP-помощники (в лог не попадают URL и параметры — там может быть ключ)
# ============================================================

def _http_get(url: str, params: dict, name: str,
              headers: Optional[dict] = None) -> Optional[requests.Response]:
    try:
        resp = requests.get(
            url, params=params, headers=headers,
            timeout=(config.WEATHER_CONNECT_TIMEOUT, config.WEATHER_HTTP_TIMEOUT),
        )
        resp.raise_for_status()
        return resp
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        logger.error("%s: HTTP %s", name, status)
    except requests.RequestException as e:
        logger.error("%s: request failed (%s)", name, type(e).__name__)
    return None


def _get_json(url: str, params: dict, name: str,
              headers: Optional[dict] = None) -> Optional[dict]:
    resp = _http_get(url, params, name, headers)
    if resp is None:
        return None
    try:
        return resp.json()
    except ValueError:
        logger.error("%s: invalid JSON in response", name)
        return None


def _get_text(url: str, params: dict, name: str,
              headers: Optional[dict] = None) -> Optional[str]:
    resp = _http_get(url, params, name, headers)
    return resp.text if resp is not None else None


def _observed_only(records: list[dict], now: Optional[datetime] = None) -> list[dict]:
    """Оставляет только наступившие часы (отбрасывает прогноз)."""
    now = now or datetime.now(timezone.utc)
    return [r for r in records if r["time"] <= now]


# ============================================================
# Провайдеры
# ============================================================

def _fetch_met_norway(lat: float, lon: float) -> list[dict]:
    """MET Norway locationforecast: первая запись ряда — текущий час.

    Правила сервиса: идентифицирующий User-Agent, координаты не точнее 4 знаков,
    разумная частота запросов (раз в час — с запасом).
    """
    params = {"lat": round(lat, 4), "lon": round(lon, 4)}
    data = _get_json(config.WEATHER_MET_URL, params, "MET Norway",
                     headers={"User-Agent": config.WEATHER_USER_AGENT})
    if not data:
        return []

    result: list[dict] = []
    for entry in (data.get("properties") or {}).get("timeseries", []):
        try:
            dt = datetime.fromisoformat(entry["time"].replace("Z", "+00:00"))
            details = entry["data"]["instant"]["details"]
        except (KeyError, TypeError, ValueError):
            continue
        temp = details.get("air_temperature")
        hum = details.get("relative_humidity")
        if temp is None and hum is None:
            continue
        result.append({"time": dt.astimezone(timezone.utc),
                       "temperature": temp, "humidity": hum})
    return result


_WTTR_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*°?\s*C\s*\|\s*(\d+(?:\.\d+)?)\s*%")


def _fetch_wttr(lat: float, lon: float) -> list[dict]:
    """wttr.in, формат '%t|%h' (например '+13°C|54%'). Снимок текущего часа."""
    url = f"{config.WEATHER_WTTR_URL}/{lat},{lon}"
    text = _get_text(url, {"format": "%t|%h", "m": ""}, "wttr.in",
                     headers={"User-Agent": config.WEATHER_USER_AGENT})
    if not text:
        return []

    m = _WTTR_RE.search(text)
    if not m:
        logger.error("wttr.in: unexpected response format")
        return []

    hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [{"time": hour,
             "temperature": float(m.group(1)),
             "humidity": float(m.group(2))}]


def _fetch_open_meteo(lat: float, lon: float) -> list[dict]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,relative_humidity_2m",
        "past_hours": config.WEATHER_PAST_HOURS,
        "forecast_hours": 1,   # текущий час; всё, что позже, всё равно отфильтруется
        "timezone": "GMT",     # время в ответе сразу в UTC
    }
    data = _get_json(config.WEATHER_OPEN_METEO_URL, params, "Open-Meteo")
    if not data:
        return []

    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    hums = hourly.get("relative_humidity_2m") or []

    result: list[dict] = []
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        temp = temps[i] if i < len(temps) else None
        hum = hums[i] if i < len(hums) else None
        if temp is None and hum is None:
            continue
        result.append({"time": dt, "temperature": temp, "humidity": hum})
    return result


def _fetch_weatherapi(lat: float, lon: float) -> list[dict]:
    if not config.WEATHER_API_KEY:
        return []

    params = {
        "key": config.WEATHER_API_KEY,
        "q": f"{lat},{lon}",
        "days": 1,
    }
    data = _get_json(config.WEATHER_API_URL, params, "WeatherAPI.com")
    if not data:
        return []

    error = data.get("error")
    if error:
        logger.error("WeatherAPI.com error: %s", error.get("message"))
        return []

    # Время от API — в часовом поясе локации (tz_id).
    tz_id = (data.get("location") or {}).get("tz_id") or config.WEATHER_TIMEZONE
    try:
        tz = ZoneInfo(tz_id)
    except ZoneInfoNotFoundError:
        tz = timezone.utc

    result: list[dict] = []
    for day in (data.get("forecast") or {}).get("forecastday", []):
        for h in day.get("hour", []):
            time_str = h.get("time")
            if not time_str:
                continue
            try:
                dt = datetime.fromisoformat(time_str).replace(tzinfo=tz).astimezone(timezone.utc)
            except ValueError:
                continue
            result.append({
                "time": dt,
                "temperature": h.get("temp_c"),
                "humidity": h.get("humidity"),
            })
    return result


# Порядок задаёт очередь запасных провайдеров.
_PROVIDERS: dict[str, Callable[[float, float], list[dict]]] = {
    "wttr": _fetch_wttr,
    "met-norway": _fetch_met_norway,
    "open-meteo": _fetch_open_meteo,
    "weatherapi": _fetch_weatherapi,
}


def fetch_hourly_weather(
    lat: float | None = None,
    lon: float | None = None,
) -> list[dict]:
    """Возвращает почасовые наблюдения погоды.

    Пробует основного провайдера, при пустом результате — запасных по очереди.

    Returns:
        Список dict: {'time': datetime (UTC), 'temperature': float, 'humidity': float}
        только за наступившие часы. Пустой список, если данных получить не удалось.
    """
    lat = config.WEATHER_LAT if lat is None else lat
    lon = config.WEATHER_LON if lon is None else lon

    primary = config.WEATHER_PROVIDER
    if primary not in _PROVIDERS:
        logger.error("Unknown weather provider: %s", primary)
    order = ([primary] if primary in _PROVIDERS else []) + \
            [p for p in _PROVIDERS if p != primary]

    for name in order:
        if name == "weatherapi" and not config.WEATHER_API_KEY:
            continue

        records = _observed_only(_PROVIDERS[name](lat, lon))
        if records:
            logger.info("%s: %d observed hourly records", name, len(records))
            return records
        logger.warning("%s: no usable data", name)

    return []


def fetch_current_weather(
    lat: float | None = None,
    lon: float | None = None,
) -> Optional[dict]:
    """Последнее наблюдённое почасовое значение (или None)."""
    records = fetch_hourly_weather(lat, lon)
    if not records:
        return None
    return dict(max(records, key=lambda r: r["time"]))
