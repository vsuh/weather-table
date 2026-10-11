"""Тест выбора погодных наблюдений (без сети и БД). Запуск: python test_weather.py"""

import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

import config
from collector import weather

NOW = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def iso(h, z=False):
    s = (NOW + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M")
    return s + ":00Z" if z else s


def check(name, cond):
    print(f"{'OK  ' if cond else 'FAIL'} {name}")
    return cond


def main():
    config.WEATHER_API_KEY = ""          # запасной WeatherAPI отключён
    results = []

    # --- MET Norway: ряд от текущего часа вперёд, остаётся только текущий час
    met = {"properties": {"timeseries": [
        {"time": iso(h, True),
         "data": {"instant": {"details": {
             "air_temperature": 10.0 + h, "relative_humidity": 70.0 + h}}}}
        for h in (0, 1, 2, 3)
    ]}}
    config.WEATHER_PROVIDER = "met-norway"
    weather._get_json = lambda url, params, name, headers=None: met
    weather._get_text = lambda *a, **k: None
    recs = weather.fetch_hourly_weather()
    results.append(check("MET: только текущий час (прогноз отброшен)",
                         len(recs) == 1 and recs[0]["time"] == NOW))
    results.append(check("MET: значения T=10.0 RH=70.0",
                         recs[0]["temperature"] == 10.0 and recs[0]["humidity"] == 70.0))
    results.append(check("MET: время aware-UTC",
                         recs[0]["time"].utcoffset() == timedelta(0)))

    # --- wttr.in: строка '+13°C|54%' -> снимок текущего часа
    weather._get_json = lambda *a, **k: None          # MET недоступен
    weather._get_text = lambda url, params, name, headers=None: "+13°C|54%\n"
    recs = weather.fetch_hourly_weather()              # запасной wttr
    results.append(check("wttr (запасной): T=13.0 RH=54.0, час = текущий",
                         len(recs) == 1 and recs[0]["temperature"] == 13.0
                         and recs[0]["humidity"] == 54.0 and recs[0]["time"] == NOW))

    weather._get_text = lambda url, params, name, headers=None: "-5.5°C|100%"
    recs = weather.fetch_hourly_weather()
    results.append(check("wttr: отрицательная температура -5.5",
                         recs and recs[0]["temperature"] == -5.5))

    # --- Open-Meteo: история, будущие часы отбрасываются
    om = {"hourly": {
        "time": [iso(h) for h in (-2, -1, 0, 1, 2)],
        "temperature_2m": [1.0, 2.0, 3.0, 4.0, 5.0],
        "relative_humidity_2m": [90, 91, 92, 93, 94],
    }}
    config.WEATHER_PROVIDER = "open-meteo"
    weather._get_json = lambda url, params, name, headers=None: om
    recs = weather.fetch_hourly_weather()
    results.append(check("Open-Meteo: 3 наступивших часа (-2, -1, 0)",
                         len(recs) == 3 and max(r["time"] for r in recs) == NOW))

    # --- Все провайдеры недоступны / мусор -> [] без исключения
    weather._get_json = lambda *a, **k: None
    weather._get_text = lambda url, params, name, headers=None: "Unknown location"
    results.append(check("Все недоступны или мусор -> []",
                         weather.fetch_hourly_weather() == []))

    # --- Неизвестный основной провайдер не ломает цепочку
    config.WEATHER_PROVIDER = "nope"
    weather._get_text = lambda url, params, name, headers=None: "+1°C|50%"
    results.append(check("Неизвестный провайдер -> работают запасные",
                         len(weather.fetch_hourly_weather()) == 1))

    ok = all(results)
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


main()
