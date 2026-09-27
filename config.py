"""Конфигурация приложения."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

# --- Sensors ---
# Список датчиков описывается в sensors.yaml (см. collector/registry.py)
SENSORS_FILE: Path = BASE_DIR / os.getenv("SENSORS_FILE", "sensors.yaml")

# --- BLE ---
# UUID сервиса ATC Custom firmware (PVWX format)
ATC_SERVICE_UUID: str = "0000181a-0000-1000-8000-00805f9b34fb"
# UUID сервиса BTHome v2 (альтернативный формат ATC)
BTHOME_SERVICE_UUID: str = "0000181c-0000-1000-8000-00805f9b34fb"
# UUID чарактеристики BTHome (GATT)
BTHOME_CHAR_UUID: str = "00002a2f-0000-1000-8000-00805f9b34fb"

# --- Weather provider ---
# Координаты локации для уличной погоды (задаются в .env)
WEATHER_LAT: float = float(os.getenv("WEATHER_LAT", "55.7558"))
WEATHER_LON: float = float(os.getenv("WEATHER_LON", "37.6173"))
WEATHER_TIMEZONE: str = os.getenv("WEATHER_TIMEZONE", "Europe/Moscow")
# Как часто обновлять прогноз (сек).
WEATHER_POLL_SECONDS: int = int(os.getenv("WEATHER_POLL_SECONDS", "3600"))
# WeatherAPI.com (бесплатный: 1000 запросов/день).
# Ключ получить на https://www.weatherapi.com/
WEATHER_API_KEY: str = os.getenv("WEATHER_API_KEY", "")
WEATHER_API_URL: str = "https://api.weatherapi.com/v1/forecast.json"
# Circuit-breaker: макс. время ожидания при сбоях (сек).
# После N последовательных ошибок интервал увеличивается экспоненциально.
WEATHER_MAX_BACKOFF_SECONDS: int = int(os.getenv("WEATHER_MAX_BACKOFF_SECONDS", "3600"))
WEATHER_BACKOFF_MULTIPLIER: int = int(os.getenv("WEATHER_BACKOFF_MULTIPLIER", "2"))
WEATHER_BACKOFF_BASE_SECONDS: int = int(os.getenv("WEATHER_BACKOFF_BASE_SECONDS", "60"))

# --- Database ---
DB_DIR: Path = BASE_DIR / "data"
DB_PATH: Path = DB_DIR / "weather.db"

# --- API ---
API_HOST: str = "0.0.0.0"
API_PORT: int = 8000

# --- Collection ---
# BLE-датчик шлёт пакеты ~1/с. Измерения копятся в окне, затем
# сворачиваются в средние значения и пишутся одной записью в БД.
AGGREGATION_WINDOW_SECONDS: int = int(
    os.getenv("AGGREGATION_WINDOW_SECONDS", 60)
)

# --- Health / monitoring ---
# Показание считается «устаревшим», если с его времени прошло больше порога.
# Для BLE берём запас в 5 окон агрегации (но не меньше 5 минут).
HEALTH_BLE_STALE_SECONDS: int = int(
    os.getenv("HEALTH_BLE_STALE_SECONDS", str(max(AGGREGATION_WINDOW_SECONDS * 5, 300)))
)
# Для погоды — два интервала опроса (но не меньше 2 часов).
HEALTH_WEATHER_STALE_SECONDS: int = int(
    os.getenv("HEALTH_WEATHER_STALE_SECONDS", str(max(WEATHER_POLL_SECONDS * 2, 7200)))
)

# --- Logging ---
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
# Формат логов: 'text' (человекочитаемый) | 'json' (для сбора/парсинга).
LOG_FORMAT: str = os.getenv("LOG_FORMAT", "text")

# --- Retention ---
# Хранить показания N дней (0 = без ограничений).
RETENTION_DAYS: int = int(os.getenv("RETENTION_DAYS", "0"))
# Как часто запускать очистку (сек). По умолчанию — раз в час.
RETENTION_CHECK_INTERVAL: int = int(
    os.getenv("RETENTION_CHECK_INTERVAL", "3600")
)
