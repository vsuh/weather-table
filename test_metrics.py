"""Тест метрик Prometheus на временной БД. Запуск: python test_metrics.py"""

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, ".")

import config

_tmp = Path(tempfile.mkdtemp())
config.DB_DIR = _tmp
config.DB_PATH = _tmp / "test.db"

from storage.database import get_session, init_db           # noqa: E402
from storage.models import Reading, Sensor                   # noqa: E402
from api.metrics import render_metrics                       # noqa: E402


def check(name, cond):
    print(f"{'OK  ' if cond else 'FAIL'} {name}")
    return cond


def value_of(lines, metric, sensor_id):
    """Значение метрики с меткой sensor_id (или None)."""
    for line in lines:
        if line.startswith(metric + "{") and f'sensor_id="{sensor_id}"' in line:
            return float(line.rsplit(" ", 1)[1])
    return None


def main():
    init_db()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    with get_session() as s:
        s.add(Sensor(id="b", name="BLE", location="room", source="ble", active=True))
        s.add(Sensor(id="w", name="Улица", location="outdoor", source="weather", active=True))
        s.add(Reading(sensor_id="b", source="ble", temperature=24.0, humidity=40.0,
                      battery=90, battery_mv=2900, packets_count=8,
                      recorded_at=now - timedelta(seconds=60)))
        s.add(Reading(sensor_id="w", source="weather", temperature=10.0, humidity=80.0,
                      packets_count=1, recorded_at=now - timedelta(minutes=30)))
        s.add(Reading(sensor_id="w", source="weather", temperature=99.0, humidity=99.0,
                      packets_count=1, recorded_at=now + timedelta(hours=2)))   # прогноз

    ok = []

    # Два запроса подряд: раньше второй (и даже первый) падал на сбросе меток
    data, ctype = render_metrics()
    data, ctype = render_metrics()
    text = data.decode()
    lines = text.splitlines()
    ok.append(check("render_metrics дважды без исключений", bool(text)))
    ok.append(check("weather_db_up = 1", "weather_db_up 1.0" in lines))

    ok.append(check("температура BLE = 24.0", value_of(lines, "weather_temperature_celsius", "b") == 24.0))
    ok.append(check("влажность BLE = 40.0", value_of(lines, "weather_humidity_percent", "b") == 40.0))
    ok.append(check("батарея 90 % и 2900 мВ",
                    value_of(lines, "weather_battery_percent", "b") == 90.0
                    and value_of(lines, "weather_battery_millivolts", "b") == 2900.0))
    temps = [float(l.rsplit(" ", 1)[1]) for l in lines
             if l.startswith("weather_temperature_celsius{")]
    ok.append(check("улица: берётся наступившая запись (10.0), а не прогноз (99.0)",
                    value_of(lines, "weather_temperature_celsius", "w") == 10.0
                    and 99.0 not in temps))

    age_b = value_of(lines, "weather_readings_latest_age_s", "b")
    ok.append(check("возраст последнего показания BLE около 60 с", age_b is not None and 55 <= age_b <= 120))
    age_w = value_of(lines, "weather_readings_latest_age_s", "w")
    ok.append(check("возраст погоды около 30 минут (не отрицательный)",
                    age_w is not None and 1700 <= age_w <= 1900))

    ok.append(check("записей за последний час: по 1 (будущая не считается)",
                    value_of(lines, "weather_readings_last_hour", "b") == 1.0
                    and value_of(lines, "weather_readings_last_hour", "w") == 1.0))
    ok.append(check("число датчиков по source",
                    'weather_sensors_total{source="ble"} 1.0' in lines
                    and 'weather_sensors_total{source="weather"} 1.0' in lines))

    allok = all(ok)
    print(f"\nRESULT: {'PASS' if allok else 'FAIL'}")
    sys.exit(0 if allok else 1)


main()
