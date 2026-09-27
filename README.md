---
project: Weather Table
created: "2026-09-24"
related: "[[10-projects/index|index]]"
title: График погоды в спальне (README)
---
# Weather Table

Система сбора почасовых данных с BLE-датчика температуры и влажности Xiaomi LYWSD03MMC (ATC firmware) с хранением в SQLite и веб-дашбордом.

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

## Быстрый старт

### 1. Датчик

Датчик **LYWSD03MMC** (MAC `A4:C1:38:20:64:92`) перепрошит на ATC_MiThermometer v5.9, протокол Custom (без шифрования).

### 2. Установка зависимостей

```bash
cd weather-table
python -m venv .venv
.venv\Scripts\activate        # Windows
# или
source .venv/bin/activate     # Linux

pip install -r requirements.txt
```

### 3. Конфигурация

Основные параметры в `config.py`:

| Параметр | Значение по умолчанию | Описание |
|---|---|---|
| `SENSOR_MAC` | `A4:C1:38:20:64:92` | MAC-адрес датчика |
| `AGGREGATION_WINDOW_SECONDS` | `60` | Окно усреднения (сек) |
| `API_HOST` | `0.0.0.0` | Хост API |
| `API_PORT` | `8000` | Порт API |

Переопределяются через `.env`:

```env
AGGREGATION_WINDOW_SECONDS=60
LOG_LEVEL=INFO
```

### 4. Запуск

#### Коллектор (сбор + агрегация)

```bash
python collector/main.py
```

#### API + Дашборд

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

Дашборд доступен по `http://localhost:8000/`

## REST API

| Endpoint | Метод | Описание |
|---|---|---|
| `/api/readings` | GET | Последние N показаний |
| `/api/readings/latest` | GET | Самое свежее показание |
| `/api/stats/summary` | GET | Min/Max/Avg статистика |
| `/api/readings/time-series?hours=24` | GET | Данные для графика |

Пример запроса:
```bash
curl http://localhost:8000/api/readings/latest
# {
#   "id": 42,
#   "sensor_mac": "A4:C1:38:20:64:92",
#   "temperature": 23.5,
#   "humidity": 45.2,
#   "battery_mv": 3200,
#   "battery": 87,
#   "packets_count": 65,
#   "recorded_at": "2026-09-22T13:30:00+00:00"
# }
```

## Деплой на HELOR (Ubuntu 24.04)

### 1. Развертывание

```bash
cd /home/ubuntu/weather-table

# Виртуальное окружение
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. systemd сервисы

**Коллектор:**
```bash
sudo cp systemd/weather-collector.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now weather-collector
```

**API:**
```bash
sudo cp systemd/weather-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now weather-api
```

### 3. Проверка

```bash
curl http://localhost:8000/api/readings/latest
# Открыть http://<HELOR_IP>:8000/
```

### 4. Логи

```bash
journalctl -u weather-collector -f
journalctl -u weather-api -f
```

## Структура проекта

```
weather-table/
├── collector/
│   ├── ble_reader.py      # Сканирование BLE (bleak)
│   ├── parser.py           # Парсер ATC Custom + BTHome
│   ├── aggregator.py       # Dedup, накопление, усреднение
│   └── main.py             # Точка входа коллектора
├── storage/
│   ├── models.py           # SQLAlchemy модели
│   └── database.py         # Инициализация БД
├── api/
│   ├── main.py             # FastAPI приложение
│   └── templates/
│       └── dashboard.html  # Chart.js дашборд
├── systemd/                # systemd unit files
├── scan.py                 # Скрипт диагностики BLE
├── p.py                    # Тестовый парсер пакетов
├── test_aggregator.py      # Тест логики агрегации
├── config.py               # Конфигурация
├── requirements.txt
└── task.md                 # Описание задачи
```

## Диагностика

### Тест логики агрегации

```bash
python test_aggregator.py
# Проверяет dedup по counter: 5 пакетов -> 2 уникальных измерения + 3 дубликата
```

### Скрипт сканирования `scan.py`

Использовать на HELOR для отладки BLE:

```bash
cd /home/ubuntu/weather-table
source .venv/bin/activate

# Сканировать бродкасты 10 секунд
python scan.py

# Сканировать 30 секунд
python scan.py --duration 30

# Непрерывный режим
python scan.py --continuous

# Тестовый пакет (локально, без BLE)
python p.py
python p.py 92642038c1a46c094c183c36570500
```

### Настройка Bluetooth на HELOR

```bash
# Проверить адаптер
bluetoothctl show

# Включить
sudo systemctl start bluetooth
sudo bluetoothctl power on

# Проверить видимость датчика (btmgmt)
sudo btmgmt find

# Добавить пользователя в группу bluetooth
sudo usermod -aG bluetooth ubuntu
```

### Возможные проблемы

| Проблема | Решение |
|---|---|
| `No adapters found` | `sudo systemctl start bluetooth` |
| `Permission denied` | `sudo usermod -aG bluetooth $USER` + перезаход |
| Датчик не виден | Проверить LED (должен мигать), `sudo btmgmt find` |
| `bleak` не установлен | `pip install bleak` |

## Форматы данных датчика

### ATC Custom (UUID 0x181A) — текущий формат

Формат бродкаста (15+ байт):

| Смещение | Поле | Размер | Тип | Единица |
|---|---|---|---|---|
| 0..5 | MAC | 6B | — | — |
| 6..7 | Температура | 2B | int16 LE | /100 °C |
| 8..9 | Влажность | 2B | uint16 LE | /100 % |
| 10..11 | Батарея мВ | 2B | uint16 LE | mV |
| 12 | Батарея % | 1B | uint8 | % |
| 13 | Counter | 1B | uint8 | — |
| 14 | Flags | 1B | uint8 | — |

Пример пакета:
```
92 64 20 38 c1 a4 6c 09 4c 18 3c 36 87 05 00
MAC        T=24.12  RH=62.2  BAT=13756mV 87%  CNT=5  FLG=0x00
```

### BTHome v2 (UUID 0x181C) — альтернативный формат ATC

| Data ID | Поле | Размер | Единица |
|---|---|---|---|
| `0x0001` | Температура | 2B signed | 0.01°C |
| `0x0002` | Влажность | 2B unsigned | 0.01% |
| `0x000B` | Батарея | 1B | % |

Подробнее: https://bthome.io/

## Алгоритм агрегации

Коллектор работает непрерывно:

1. **BLE-скан** — bleak `detection_callback` ловит каждый пакет
2. **Dedup** — если `counter` изменился, это новое измерение; если тот же — пакет дубликат
3. **Накопление** — пакеты с одинаковым counter складываются в окно (по умолчанию 60 сек)
4. **Свёртка** — средние значения температуры, влажности, батареи за окно
5. **Запись** — одно усреднённое показание в БД с `packets_count`

Результат: ~60 показаний в день (1 на минуту) вместо ~86400 сырых пакетов.
