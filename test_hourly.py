"""Тест почасовой выборки API на временной БД. Запуск: python test_hourly.py"""

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, ".")

import config

_tmp = Path(tempfile.mkdtemp())
config.DB_DIR = _tmp
config.DB_PATH = _tmp / "test.db"

from storage.database import get_session, init_db          # noqa: E402
from storage.models import Reading, Sensor                  # noqa: E402
from api import main as api_main                            # noqa: E402


def check(name, cond):
    print(f"{'OK  ' if cond else 'FAIL'} {name}")
    return cond


def main():
    init_db()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    h0 = now.replace(minute=0, second=0, microsecond=0)       # начало текущего часа

    def add(session, minutes, temp, hum):
        session.add(Reading(
            sensor_id="t", source="ble", temperature=temp, humidity=hum,
            packets_count=8, recorded_at=h0 + timedelta(minutes=minutes),
        ))

    with get_session() as s:
        s.add(Sensor(id="t", name="Тест", location="test", source="ble", active=True))
        add(s, -50, 20.0, 40.0)          # час H-1
        add(s, -20, 22.0, 50.0)          # час H-1
        add(s, 0, 24.0, 60.0)            # текущий час (recorded_at == начало часа, <= now)
        add(s, -300, 10.0, 10.0)         # час H-5: вне окна hours=3
        add(s, 120, 99.0, 99.0)          # будущее (прогноз): учитываться не должно

    res = api_main.hourly(hours=3, sensor_id="t", all_sensors=False)
    ok = []

    ts = res["timestamps"]
    ok.append(check("2 часа с данными (H-1 и текущий)", len(ts) == 2))
    ok.append(check("времена в UTC с суффиксом Z", all(t.endswith(":00:00Z") for t in ts)))
    ok.append(check("часы идут по возрастанию", ts == sorted(ts)))
    ok.append(check("H-1: среднее T=21.0, min=20.0, max=22.0",
                    res["temperatures"][0] == 21.0 and res["temp_min"][0] == 20.0
                    and res["temp_max"][0] == 22.0))
    ok.append(check("H-1: среднее RH=45.0", res["humidities"][0] == 45.0))
    ok.append(check("H-1: 2 записи, 16 измерений",
                    res["readings"][0] == 2 and res["packets"][0] == 16))
    ok.append(check("текущий час: T=24.0, 1 запись",
                    res["temperatures"][1] == 24.0 and res["readings"][1] == 1))
    ok.append(check("прогноз из будущего (99) не попал в выборку",
                    99.0 not in res["temperatures"]))
    ok.append(check("запись за пределами окна (H-5) не попала",
                    10.0 not in res["temperatures"]))

    # all_sensors: структура с именем и серией
    allres = api_main.hourly(hours=3, sensor_id=None, all_sensors=True)
    ok.append(check("all_sensors: ключ датчика и name",
                    "t" in allres and allres["t"]["name"] == "Тест"
                    and len(allres["t"]["timestamps"]) == 2))

    # без sensor_id и all_sensors -> 400
    bad = api_main.hourly(hours=3, sensor_id=None, all_sensors=False)
    ok.append(check("без sensor_id -> HTTP 400", getattr(bad, "status_code", None) == 400))

    # Z-суффикс у остальных эндпоинтов (для корректного часового пояса в браузере)
    ok.append(check("_iso_utc: суффикс Z",
                    api_main._iso_utc(datetime(2026, 10, 11, 9, 0, 0)) == "2026-10-11T09:00:00Z"))
    latest = api_main.latest_reading(sensor_id="t")
    ok.append(check("latest: recorded_at с Z и не из будущего",
                    isinstance(latest, dict) and latest["recorded_at"].endswith("Z")
                    and latest["temperature"] == 24.0))

    # Статус здоровья: работает без DetachedInstanceError (объекты Sensor используются после закрытия сессии)
    report = api_main._health_report()
    ok.append(check("_health_report работает (без DetachedInstanceError), 1 датчик",
                    len(report["sensors"]) == 1 and report["sensors"][0]["sensor_id"] == "t"
                    and report["status"] in ("ok", "stale", "no_data")))

    # Дашборд: шаблон рендерится (раньше давал 500 из-за удалённой в Starlette 1.x старой сигнатуры)
    from starlette.requests import Request
    fake_request = Request({
        "type": "http", "method": "GET", "path": "/", "headers": [],
        "query_string": b"", "server": ("test", 80), "scheme": "http",
    })
    page = api_main.dashboard(fake_request)
    body = bytes(page.body).lower()
    ok.append(check("дашборд рендерится: 200 и HTML, есть переключатель разрешения",
                    page.status_code == 200 and b"<html" in body and b"res-controls" in body))

    allok = all(ok)
    print(f"\nRESULT: {'PASS' if allok else 'FAIL'}")
    sys.exit(0 if allok else 1)


main()
