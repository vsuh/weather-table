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

# --- Weather provider ---
# Координаты локации для уличной погоды (задаются в .env)
WEATHER_LAT: float = float(os.getenv("WEATHER_LAT", "55.7558"))
WEATHER_LON: float = float(os.getenv("WEATHER_LON", "37.6173"))
WEATHER_TIMEZONE: str = os.getenv("WEATHER_TIMEZONE", "Europe/Moscow")
# Как часто опрашивать провайдера (сек).
WEATHER_POLL_SECONDS: int = int(os.getenv("WEATHER_POLL_SECONDS", "3600"))
# Основной провайдер: 'wttr' | 'met-norway' | 'open-meteo' | 'weatherapi'.
# Остальные пробуются по порядку как запасные (WeatherAPI — только если задан ключ).
# MET Norway и wttr.in дают снимок текущего часа, Open-Meteo — ещё и историю.
# MET Norway — глобальная модель (в наблюдениях для Москвы занижает T на ~1 °C и завышает RH),
# wttr.in лучше совпадает с бытовыми сервисами.
WEATHER_PROVIDER: str = os.getenv("WEATHER_PROVIDER", "wttr").strip().lower()
# Сколько часов в прошлое запрашивать у Open-Meteo (только он отдаёт историю). Хранятся только
# наступившие часы (факт), будущие (прогноз) отбрасываются. Для разового
# дозаполнения истории можно временно поставить, например, 400.
WEATHER_PAST_HOURS: int = int(os.getenv("WEATHER_PAST_HOURS", "48"))
# Таймауты HTTP-запроса к провайдеру (сек): на подключение и на чтение ответа.
WEATHER_CONNECT_TIMEOUT: int = int(os.getenv("WEATHER_CONNECT_TIMEOUT", "5"))
WEATHER_HTTP_TIMEOUT: int = int(os.getenv("WEATHER_HTTP_TIMEOUT", "20"))
# MET Norway требует идентифицирующий User-Agent (приложение + контакт).
WEATHER_USER_AGENT: str = os.getenv(
    "WEATHER_USER_AGENT", "weather-table/1.0 github.com/vsuh"
)
WEATHER_MET_URL: str = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
WEATHER_WTTR_URL: str = "https://wttr.in"
WEATHER_OPEN_METEO_URL: str = "https://api.open-meteo.com/v1/forecast"
# WeatherAPI.com (запасной, бесплатный: 1000 запросов/день). Ключ необязателен.
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
