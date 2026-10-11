---
project: Weather Table
created: "2026-09-24"
updated: "2026-10-11"
related: "[[10-projects/index|index]]"
title: Weather Table — сбор температуры и влажности (README)
---
# Weather Table

Система сбора данных о температуре и влажности: несколько BLE-датчиков Xiaomi LYWSD03MMC (прошивка ATC/pvvx) плюс уличная погода из интернета. Данные усредняются, хранятся в SQLite и показываются в веб-дашборде (Chart.js) и Grafana.

## Архитектура

```
┌──────────────┐  BLE   ┌──────────────────┐     ┌──────────────┐
│ BLE-датчики  │───────▶│                  │     │              │      ┌─────────────┐
│ living_room  │        │   Aggregator     │────▶│  SQLite DB   │─────▶│ FastAPI     │
│ storage      │        │ (dedup + avg)    │     │  weather.db  │      │ /api, /     │
└──────────────┘        │                  │     │              │      │ /health     │
┌──────────────┐  HTTP  │  weather loop    │     │              │      │ /metrics    │
│ Погода (wttr,│───────▶│ (раз в час,      │     └──────────────┘      └──────┬──────┘
│ MET, ...)    │        │  только факт)    │                                  │
└──────────────┘        └──────────────────┘                          Prometheus → Grafana
```

Датчики описываются в `sensors.yaml`, один процесс-коллектор (`collector/main.py`) обслуживает все.

## Датчики

Список — в `sensors.yaml`:

| id | Название | Источник | Адрес / провайдер |
|---|---|---|---|
| `living_room` | Комната | BLE (`atc`) | `A4:C1:38:20:64:92` |
| `storage` | Кладовка | BLE (`atc`) | `A4:C1:38:3D:B6:AF` |
| `outdoor` | Улица | weather | см. раздел «Уличная погода» |

Оба BLE-датчика перепрошиты на **ATC_MiThermometer (pvvx)**, формат рассылки *pvvx custom* (UUID `0x181A`, без шифрования). После прошивки датчики видны под именами `ATC_206492` и `ATC_3DB6AF` (последние три байта MAC).

Новый датчик: добавить запись в `sensors.yaml` и перезапустить коллектор (таблица `sensors` синхронизируется при старте).

## Быстрый старт

### 1. Установка зависимостей

```bash
cd weather-table
python3 -m venv .venv
source .venv/bin/activate        # Linux
# .venv\Scripts\activate         # Windows
pip install -r requirements.txt
```

### 2. Конфигурация

Параметры читаются из `config.py` и переопределяются через `.env` (файл не публиковать, он в `.gitignore`).

| Переменная | По умолчанию | Описание |
|---|---|---|
| `AGGREGATION_WINDOW_SECONDS` | `60` | Окно усреднения BLE-пакетов (сек). На HELOR стоит `180` |
| `WEATHER_PROVIDER` | `wttr` | Основной погодный провайдер: `wttr`, `met-norway`, `open-meteo`, `weatherapi` |
| `WEATHER_POLL_SECONDS` | `3600` | Как часто опрашивать погоду |
| `WEATHER_LAT`, `WEATHER_LON` | `55.7558`, `37.6173` | Координаты уличной погоды |
| `WEATHER_TIMEZONE` | `Europe/Moscow` | Часовой пояс локации |
| `WEATHER_API_KEY` | пусто | Ключ WeatherAPI.com (необязателен, запасной провайдер) |
| `WEATHER_USER_AGENT` | `weather-table/1.0 github.com/vsuh` | User-Agent для MET Norway и wttr.in |
| `WEATHER_CONNECT_TIMEOUT`, `WEATHER_HTTP_TIMEOUT` | `5`, `20` | Таймауты HTTP-запросов к погоде (сек) |
| `WEATHER_PAST_HOURS` | `48` | Глубина истории у Open-Meteo (часов) |
| `RETENTION_DAYS` | `0` | Хранить показания N дней (0 — без ограничений) |
| `LOG_LEVEL`, `LOG_FORMAT` | `INFO`, `text` | Уровень и формат логов (`text` или `json`) |

### 3. Запуск

```bash
python collector/main.py                                   # коллектор (BLE + погода)
uvicorn api.main:app --host 0.0.0.0 --port 8000            # API + дашборд
```

Дашборд: `http://localhost:8000/`.

## Уличная погода (`outdoor`)

Уличный датчик хранит **наблюдённые значения** (факт), а не прогноз: часы, которые ещё не наступили, отбрасываются. Записи делаются раз в час по принципу upsert (час уже есть — значения обновляются).

| Провайдер | Что отдаёт | Заметки |
|---|---|---|
| `wttr` (основной) | снимок текущего часа | wttr.in, компактный формат `%t\|%h`; JSON-режим `j1` с HELOR тормозит и не используется |
| `met-norway` | снимок текущего часа | api.met.no, нужен User-Agent; модель занижает T в Москве примерно на 1 °C |
| `open-meteo` | история за `WEATHER_PAST_HOURS` часов | **с HELOR недоступен** (соединение с `api.open-meteo.com:443` не устанавливается) |
| `weatherapi` | почасовой ряд за сегодня | только если задан `WEATHER_API_KEY`; бывают таймауты |

Если основной провайдер ничего не вернул, пробуются остальные по очереди. Если не ответил никто, включается backoff (`WEATHER_BACKOFF_*`). Ошибки провайдеров пишутся в лог без URL и ключей. Значения — модельные, не станции; по контрольным замерам (Яндекс, Google) температура совпадает до ~1 °C, влажность у разных источников расходится заметно.

Тест без сети: `python test_weather.py`.

## REST API

| Endpoint | Метод | Описание |
|---|---|---|
| `/api/sensors` | GET | Список датчиков |
| `/api/readings` | GET | Последние N показаний (`sensor_id`, `limit`, `offset`) |
| `/api/readings/latest` | GET | Самое свежее показание (`sensor_id`) |
| `/api/readings/time-series` | GET | Данные для графика по окнам агрегации (`hours` до 720, `sensor_id`, `all_sensors`) |
| `/api/readings/hourly` | GET | Почасовые min/avg/max температуры и влажности (`hours` до 2160, `sensor_id` или `all_sensors=true`) |
| `/api/stats/summary` | GET | Min/Max/Avg (`sensor_id`) |
| `/api/status`, `/health` | GET | Свежесть данных по датчикам (`/health` отвечает 503, если есть проблемы) |
| `/metrics` | GET | Метрики Prometheus |
| `/api/cleanup?days=N` | POST | Удалить показания старше N дней |

Пример:
```bash
curl "http://localhost:8000/api/readings/latest?sensor_id=living_room"
# {"id": 1062, "sensor_id": "living_room", "source": "ble",
#  "temperature": 24.95, "humidity": 36.64, "battery_mv": 2971, "battery": 96,
#  "packets_count": 8, "recorded_at": "2026-10-10T21:11:18Z"}

curl "http://localhost:8000/api/readings/hourly?hours=24&sensor_id=living_room"
# {"sensor_id": "living_room",
#  "timestamps": ["2026-10-10T21:00:00Z", ...],
#  "temperatures": [24.97, ...], "temp_min": [24.93, ...], "temp_max": [25.0, ...],
#  "humidities": [36.7, ...], "hum_min": [...], "hum_max": [...],
#  "readings": [20, ...], "packets": [160, ...]}
```

Время в БД хранится в UTC без указания пояса, в ответах API все моменты времени отдаются в UTC с суффиксом `Z` (браузер переводит их в местное время). Каждая запись BLE — среднее за окно агрегации (`packets_count` измерений). Почасовая выборка `/api/readings/hourly` группирует записи по часам UTC [HH:00, HH:59]; последний (текущий) час может быть неполным, число записей в каждом часе отдаётся в `readings`. Записи из будущего (`recorded_at` позже текущего момента) во всех выборках игнорируются. Дашборд переключает разрешение графика: «Авто» (почасовая выборка начиная с 7 дней), «По окнам», «По часам».

## Мониторинг (Prometheus / Grafana)

`/metrics` (процесс API) собирает метрики из БД при каждом запросе; записи из будущего не учитываются:

| Метрика | Метки | Описание |
|---|---|---|
| `weather_temperature_celsius` | `sensor_id`, `source`, `location` | Последняя температура |
| `weather_humidity_percent` | `sensor_id`, `source`, `location` | Последняя влажность |
| `weather_battery_percent`, `weather_battery_millivolts` | `sensor_id`, `source` | Батарея BLE-датчика |
| `weather_readings_latest_age_s` | `sensor_id`, `source` | Возраст последнего показания (сек) |
| `weather_readings_last_hour` | `sensor_id`, `source` | Записей за последний час (BLE — около 20, погода — 1) |
| `weather_readings_count` | `sensor_id`, `source` | Всего записей в БД |
| `weather_sensors_total` | `source` | Число активных датчиков |
| `weather_db_up` | — | 1, если БД доступна |

Счётчики коллектора (`weather_readings_total`, `weather_aggregation_packets`, `weather_aggregation_duplicates`) живут в процессе коллектора и в `/metrics` API не попадают (публикация отдельным портом — в планах).

Дашборд Grafana «Weather Table» (`grafana/dashboard.json`, подключается автоматически): температура и влажность сейчас и на графиках, батарея (% и мВ), возраст показаний BLE и погоды, записей за час, число датчиков, доступность БД. Точки на графиках — «последнее известное значение» на момент опроса Prometheus (раз в 15 с), то есть значения меняются ступеньками (BLE — раз в окно агрегации, погода — раз в час).

## Деплой на HELOR (Ubuntu 24.04)

Рабочая копия — `/opt/weather-table`, сервис запускается из неё (`WorkingDirectory=/opt/weather-table`, интерпретатор `/opt/weather-table/.venv/bin/python`). БД: `/opt/weather-table/data/weather.db`.

```bash
cd /opt/weather-table
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

sudo cp systemd/weather-collector.service /etc/systemd/system/
sudo cp systemd/weather-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now weather-collector weather-api
```

Проверка и логи:
```bash
systemctl status weather-collector --no-pager
journalctl -u weather-collector -f
curl http://localhost:8000/health
```

После обновления кода: подтянуть изменения в `/opt/weather-table` и `sudo systemctl restart weather-collector weather-api`. Источник истины для кода — git-репозиторий (vault); правки вносятся там и выкатываются в `/opt/weather-table`.

### Docker (опционально)

`docker-compose.yml` поднимает коллектор, API, Prometheus и Grafana: `docker compose up -d --build`. Дашборд — `:8000`, Grafana — `:3000` (логин `admin`, пароль из `GF_ADMIN_PASSWORD` в `.env`, без него compose не стартует), Prometheus — `:9090`.

- Настройки и секреты читаются из `.env` (`env_file`); в образ файл `.env`, база `data/`, `.git` и `.venv` не попадают (`.dockerignore`). `sensors.yaml` пробрасывается в контейнеры томом, пересборка при его правке не нужна.
- Для BLE коллектор запускается с `network_mode: host` и с проброшенным сокетом D-Bus (`/var/run/dbus`): `bleak` разговаривает с BlueZ хоста, поэтому на хосте должен работать `bluetooth.service`. Проверено только по конфигурации, запуск на HELOR не выполнялся (там работает systemd).
- API запускается без `--reload`, у него есть healthcheck по `/health` (503 при устаревших данных — контейнер станет `unhealthy`).
- Не запускайте Docker-стек одновременно с systemd-сервисами (порт 8000 и BLE-адаптер).

## Структура проекта

```
weather-table/
├── collector/
│   ├── main.py            # точка входа коллектора
│   ├── registry.py        # загрузка sensors.yaml
│   ├── ble_reader.py      # BLE-скан (bleak)
│   ├── parser.py          # парсеры ATC Custom и BTHome
│   ├── aggregator.py      # dedup, усреднение, запись, цикл погоды
│   └── weather.py         # погодные провайдеры (только факт)
├── storage/
│   ├── models.py          # SQLAlchemy: Sensor, Reading
│   ├── database.py        # SQLite, сессии, синхронизация датчиков
│   └── retention.py       # очистка старых данных
├── api/
│   ├── main.py            # FastAPI: REST + дашборд
│   ├── health.py          # оценка свежести данных
│   ├── metrics.py         # метрики Prometheus
│   └── templates/dashboard.html
├── grafana/, prometheus.yml, docker-compose.yml, Dockerfile, .dockerignore
├── systemd/               # unit-файлы
├── sensors.yaml           # список датчиков
├── config.py, logging_utils.py
├── scan.py                # диагностика BLE
├── p.py                   # разбор сырого пакета
├── test_aggregator.py, test_weather.py, test_hourly.py, test_metrics.py
└── task.md                # описание задачи и журнал
```

## Диагностика

### Проверка датчиков (`scan.py`)

Слушает эфир и печатает разбор пакетов только от датчиков из `sensors.yaml`:

```bash
python scan.py                     # 10 секунд
python scan.py --duration 60       # 60 секунд
python scan.py --continuous        # непрерывно
python p.py 92642038c1a46c094c183c36570500    # разобрать пакет вручную, без BLE
```

Если датчик не найден, посмотрите весь эфир без фильтра по MAC (в нём должны быть `ATC_xxxxxx`) и состояние адаптера.

### Bluetooth на HELOR

```bash
bluetoothctl show | grep -E "Powered|Controller"
sudo systemctl start bluetooth && sudo bluetoothctl power on
bluetoothctl --timeout 25 scan on | grep -iE "ATC_|A4:C1:38"
```

| Проблема | Решение |
|---|---|
| `No adapters found` | `sudo systemctl start bluetooth` |
| Датчик не виден | Слабый сигнал (RSSI около −90 дБм — предел); переставить датчик или взять USB-донгл BT 5.0 на удлинителе |
| Пакеты приходят редко | Нормально: BlueZ не отдаёт все пакеты, поэтому усреднение работает по тому, что дошло |
| Погода не обновляется | Смотреть `journalctl -u weather-collector \| grep -i weather`, проверять доступность провайдеров с HELOR |

## Форматы рассылки датчика

### ATC Custom / pvvx (UUID `0x181A`) — используется сейчас

Service data, 15 байт:

| Смещение | Поле | Размер | Тип | Единица |
|---|---|---|---|---|
| 0..5 | MAC (в обратном порядке) | 6 B | — | — |
| 6..7 | Температура | 2 B | int16 LE | /100 °C |
| 8..9 | Влажность | 2 B | uint16 LE | /100 % |
| 10..11 | Напряжение батареи | 2 B | uint16 LE | мВ |
| 12 | Заряд | 1 B | uint8 | % |
| 13 | Counter | 1 B | uint8 | — |
| 14 | Flags | 1 B | uint8 | — |

Пример реального пакета:
```
92 64 20 38 c1 a4 | 83 09 | 42 0f | 99 0b | 60 | d2 | 05
MAC (A4:C1:38:20:64:92)  24.35 °C  39.06 %  2969 мВ  96 %  counter 210  flags 0x05
```

Counter растёт на 1 с каждым новым измерением; пакеты с тем же counter — повторы, их отсекает dedup.

### BTHome v2 (UUID `0xFCD2`) — открытый стандарт, пока не используется

BTHome — открытый формат BLE-рассылки датчиков (bthome.io), который «из коробки» понимает Home Assistant. Структура service data: первый байт — device info (бит 0 — шифрование, биты 5–7 — версия, для v2 равна 2), далее объекты `[id][значение]` фиксированной длины:

| ID | Поле | Размер | Единица |
|---|---|---|---|
| `0x00` | Packet id | 1 B | — |
| `0x01` | Батарея | 1 B | % |
| `0x02` | Температура | 2 B int16 LE | 0.01 °C |
| `0x03` | Влажность | 2 B uint16 LE | 0.01 % |
| `0x0C` | Напряжение | 2 B uint16 LE | 0.001 В |

Пример: `40 02 CA 09 03 BF 13` — 25.06 °C, 50.55 %.

**Внимание:** `parse_bthome_v2()` в `collector/parser.py` и константа `BTHOME_SERVICE_UUID` (`0x181C`, это UUID устаревшего BTHome v1) пока не соответствуют спецификации v2: версия берётся из битов 4–7 вместо 5–7 (поэтому настоящие пакеты v2 отбрасываются), а ID и длина читаются как LEB128 вместо однобайтового ID с фиксированной длиной. Для текущих датчиков (`protocol: atc`) это не мешает; перед переходом на `protocol: bthome` парсер нужно переписать (см. `task.md`).

## Алгоритм агрегации

1. **BLE-скан** — `bleak` вызывает callback на каждый принятый пакет датчика.
2. **Dedup** — по `counter`: тот же counter — повтор, новый — новое измерение.
3. **Накопление** — уникальные измерения копятся в окне (`AGGREGATION_WINDOW_SECONDS`, на HELOR 180 с).
4. **Свёртка** — среднее по температуре, влажности и батарее за окно.
5. **Запись** — одна строка в `readings` с `packets_count`.

Датчик рассылает пакет примерно раз в 22–25 с, поэтому в окне 180 с обычно 6–9 измерений, то есть около 20 записей в час на датчик (≈480 в сутки). Почасовые значения отдаёт API: `/api/readings/hourly` (усреднение записей по часам UTC) и тот же режим на графике дашборда.
