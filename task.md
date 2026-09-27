# weather-table сбор данных о влажности и температуре в квартире

## Контекст и цель

В комнате установлен электронный датчик температуры и влажности от Xiaomi (Mijia) LYWSD03MMC (mac: A4:C1:38:20:64:92), который передаёт измерения по bluetooth.
Рядом стоит мини-сервер HELOR (HL) 192.168.2.2 с BT контроллером на борту. HELOR работает под управлением ОС Ubuntu 24.04.4 LTS (GNU/Linux 7.0.0-30-generic x86_64).

Требуется разработать систему сбора почасовых данных с датчиков, хранения и красивого вывода.

---

## Архитектура

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│ BLE Sensor  │────▶│ Aggregator   │────▶│  SQLite DB   │
│ (ATC fw)    │ BLE │ (dedup+avg)  │     │ weather.db   │
└─────────────┘     └──────┬───────┘     └──────┬───────┘
                           │                    │
                           │                    ├──▶ FastAPI
                           │                    │      ├── /api/...  (REST)
                           │                    │      └── /         (dashboard)
                           │                    │
                           ▼                    ▼
                      asyncio loop          Chart.js
                      (continuous)          (real-time)
```

Стек: Python (`bleak`, `FastAPI`, `sqlalchemy`), systemd для автозапуска.

Пошагово:
1. ✅ Разобраться с извлечением данных с датчика.
2. ✅ Развернуть БД и схему хранения.
3. ✅ Сервис непрерывного сбора + агрегация + systemd автозапуск.
4. ✅ REST API + веб-дашборд.
5. ✅ Логирование/мониторинг + Grafana.

---

## Журнал исследования

### Шаг 1: анализ бродкаста датчика (стоковая прошивка)

Протокол Xiaomi MiBeacon (UUID 0xFE95), данные зашифрованы AES-CCM — для чтения нужен bindkey.

### Шаг 2: получение ключа из облака Xiaomi

Через [Xiaomi-cloud-tokens-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor) получены данные датчика (в `.env`, не публиковать).

### Шаг 3: замена датчика и прошивка на ATC

Первый датчик сломался при замене батареи. Новый датчик перепрошит на **ATC_MiThermometer v5.9** (протокол Custom, без шифрования, UUID 0x181A).

**Формат ATC Custom (UUID 0x181A):**

```
[0:6]   MAC (6 bytes)
[6:8]   temperature (int16 LE, /100)
[8:10]  humidity (uint16 LE, /100)
[10:12] battery mV (uint16 LE)
[12]    battery %
[13]    counter
[14]    flags
```

Датчик транслирует ~1 пакет/сек. Несколько одинаковых пакетов с тем же counter — дубликаты одного измерения.

### Шаг 4: реализация сбора с агрегацией

Алгоритм:
1. Непрерывный BLE-скан (`bleak` `detection_callback`).
2. Dedup по counter — один counter = одно уникальное измерение.
3. Накопление уникальных измерений в окне (по умолчанию 60 сек).
4. Свёртка: средние значения температуры, влажности, батареи за окно.
5. Запись одного усреднённого показания в БД с числом измерений (`packets_count`).
6. Сброс окна, старт нового.

---

## Текущее состояние проекта

### Реализовано

| Компонент | Статус |
|---|---|
| `collector/parser.py` | ✅ `parse_atc_custom()` + `parse_bthome_v2()` |
| `collector/ble_reader.py` | ✅ Непрерывный BLE-скан (UUID 0x181A) |
| `collector/aggregator.py` | ✅ Dedup по counter, накопление, усреднение, запись |
| `collector/main.py` | ✅ Точка входа |
| `storage/models.py` | ✅ Reading с `battery_mv`, `packets_count` |
| `storage/database.py` | ✅ SQLite + session manager |
| `api/main.py` | ✅ FastAPI: `/api/readings`, `/latest`, `/stats/summary`, `/time-series` |
| `api/templates/dashboard.html` | ✅ Chart.js дашборд |
| `scan.py` | ✅ Диагностика BLE |
| `p.py` | ✅ Тестовый парсер пакетов |
| `test_aggregator.py` | ✅ Тест логики агрегации |
| `systemd/` | ✅ Сервисы для HELOR |
| `.gitignore` | ✅ Защита `.env` и данных |
| `README.md` | ✅ Документация |
| `logging_utils.py` | ✅ JSON/text логирование (единое для collector + API) |
| `api/metrics.py` | ✅ Prometheus-метрики (`/metrics`) |
| `storage/retention.py` | ✅ Политика ретеншна (удаление старых данных) |
| `grafana/` | ✅ Dashboard JSON + provisioning |
| `docker-compose.yml` | ✅ Docker-стек: collector + API + Prometheus + Grafana |
| `Dockerfile` | ✅ Контейнеризация |

### Требуется (следующие шаги)

- [ ] **Запустить коллектор на HELOR** и убедиться, что данные пишутся в БД:
       `python collector/main.py`
- [ ] **Запустить API + дашборд**, проверить графики:
       `uvicorn api.main:app --host 0.0.0.0 --port 8000`
- [ ] **Настроить systemd** автозапуск `weather-collector` и `weather-api`.
- [ ] **Проверить накопление** за сутки (сколько записей, соответствие ~60/час при окне 60с).
- [ ] **Настроить Docker-стек** (Prometheus + Grafana):
       `docker-compose up -d` → http://localhost:3000 (Grafana), http://localhost:9090 (Prometheus)
- [ ] Опционально: **алерты** при выходе температуры/влажности за пороги.

### Известные ограничения

- Датчик транслирует с интервалом ~1 сек, но `bleak` может пропускать часть пакетов — агрегация сглаживает это.
- `AGGREGATION_WINDOW_SECONDS=60` даёт ~60 записей/час. Для «почасовых» данных из ТЗ можно увеличить окно до 3600.
- При первом запуске БД создаётся автоматически в `data/weather.db`.
- Ретеншн отключён по умолчанию (`RETENTION_DAYS=0`). Установите значение > 0 для авто-очистки старых данных.
