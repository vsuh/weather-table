# AGENTS.md — Weather Table

## Quick Start

**Dev setup (Windows):**
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**Run locally:**
```bash
python collector/main.py                        # BLE collector + weather loop
uvicorn api.main:app --host 127.0.0.1 --port 8000  # FastAPI + dashboard
```

**Quick smoke tests (offline-friendly):**
```bash
python test_weather.py      # weather providers (no network required)
python test_aggregator.py   # BLE dedup + aggregation
python test_hourly.py       # hourly rollups
python test_metrics.py      # Prometheus metrics logic
```

**Run all tests:**
```bash
python -m pytest -q
```

## Architecture

**Entrypoints (real):**
- `collector/main.py` — BLE scanning, aggregation, weather polling loop. Owns the "collector" process.
- `api/main.py` — FastAPI app serving REST endpoints, dashboard (`/`), `/health`, `/metrics`.

**Module boundaries:**
- `collector/` — `ble_reader.py` (bleak), `parser.py` (ATC/pvvx custom), `aggregator.py` (dedup+windowed avg+weather loop), `weather.py` (providers), `registry.py` (load `sensors.yaml`)
- `storage/` — `database.py` (SQLite + SQLAlchemy, sensor sync on collector start), `models.py`, `retention.py`
- `api/` — `health.py`, `metrics.py`, `templates/dashboard.html`

**Sensors source of truth:** `sensors.yaml`. Collector syncs DB `sensors` on startup from this file. Adding/removing BLE sensors means updating `sensors.yaml` and restarting collector. `scan.py` also filters to MACs from `sensors.yaml`.

## BLE & Aggregation (critical)

**Protocol:** Only **ATC Custom / pvvx** (Service Data UUID `0x181A`, 15-byte). Other formats (ATC1441, BTHome, stock MiBeacon encrypted) are **not** supported. Setting `protocol: atc` is required; anything else is rejected at startup with a log error.

**Deduplication:** Packets deduped by **BLE counter** (parser field). Same counter = repeat; different counter = new measurement.

**Windowed aggregation:** Unique packets accumulate over `AGGREGATION_WINDOW_SECONDS` (default `60`; **HELOR uses `180`**). Aggregator writes **one `readings` row per window** with `temperature/humidity/battery` averaged over unique packets and `packets_count = number of unique measurements`. BLE emits ~every 22–25s, so ~6–9 unique packets in 180s window.

**Diagnostics:**
- `python scan.py` — listens and prints only packets from `sensors.yaml` MACs. Supports `--duration`, `--continuous`.
- `python p.py <hex>` — decode raw ATC custom packet manually (no BLE).

## Weather (`outdoor` sensor)

**"Only observed/fact":** Collector drops hours that are in the future. Outdoor readings are **upserted by hour** (if hour exists, values updated).

**Provider precedence & quirks:**
1. `wttr.in` (default) — compact snapshot for current hour. JSON `j1` avoided (slow on HELOR).
2. `met-norway` — needs `WEATHER_USER_AGENT`; tends to read ~1°C lower vs Moscow references.
3. `open-meteo` — historical by `WEATHER_PAST_HOURS`; **often unreachable on HELOR** (cannot connect to api.open-meteo.com:443).
4. `weatherapi.com` — needs `WEATHER_API_KEY`, may time out.

**Behavior:** Try providers in order on failure. On all failures, enable backoff (`WEATHER_BACKOFF_*`). Provider errors logged without URLs/keys.

**Config precedence:** `.env` overrides `config.py`. Key vars: `AGGREGATION_WINDOW_SECONDS`, `WEATHER_PROVIDER`, `WEATHER_POLL_SECONDS`, `WEATHER_LAT/LON`, `WEATHER_TIMEZONE`, `WEATHER_API_KEY`, `WEATHER_USER_AGENT`, `WEATHER_*_TIMEOUT`, `WEATHER_PAST_HOURS`, `RETENTION_DAYS`, `LOG_LEVEL/LOG_FORMAT`. `.env` is gitignored.

## Time Semantics (very easy to get wrong)

- **DB:** All timestamps stored in **UTC** with no timezone.
- **API:** All timestamps returned in **UTC** with `Z` suffix.
- **Filtering:** **Ignore `recorded_at > now()`** in all queries (API list/time-series/hourly/stats, health, metrics). Future timestamps must never leak into charts/metrics.
- **Hourly API:** Groups by UTC hour `[HH:00, HH:59]`. Last (current) hour may be partial; `readings` count per hour is returned.

## API, Health, Metrics

**Key endpoints:** `/api/sensors`, `/api/readings`, `/api/readings/latest`, `/api/readings/time-series`, `/api/readings/hourly`, `/api/stats/summary`, `/health`, `/status`, `/metrics`, `POST /api/cleanup?days=N`.

**Health:** `/health` returns **503** if any sensor is stale (based on last reading age).

**Prometheus `/metrics`:** Metrics computed from **DB at query time** (process API). Includes `weather_temperature_celsius`, `weather_humidity_percent`, `weather_battery_*`, `weather_readings_latest_age_s`, `weather_readings_last_hour`, `weather_readings_count`, `weather_sensors_total{source}`, `weather_db_up`. **Collector counters** (`weather_readings_total`, `weather_aggregation_packets`, `weather_aggregation_duplicates`) live only in collector process and are **not** exposed via API `/metrics`.

## Ops Gotchas

**Don't mix deployment modes:** Never run systemd collector+API **and** `docker compose --profile full` simultaneously (port 8000 conflict, BLE adapter contention, shared `data/weather.db` lock).

**Docker BLE requirements (if using profile full):** Must use `network_mode: host` and mount `/var/run/dbus` into collector container (bleak talks to host BlueZ). Host `bluetooth.service` must be active. If you see `FileNotFoundError` on D-Bus socket in collector container, the compose file is missing `/var/run/dbus` mount.

**HELOR specifics:** Live install at `/opt/weather-table`. systemd units use `WorkingDirectory=/opt/weather-table` and `/opt/weather-table/.venv/bin/python`. DB at `/opt/weather-table/data/weather.db`. On HELOR, `open-meteo` is often unreachable; prefer wttr/met-norway. Update by pulling git in `/opt/weather-table` and `systemctl restart weather-collector weather-api`.

**Grafana:** Dashboard at `grafana/dashboard.json`. Points represent "last known value" at Prometheus scrape (15s) — values step at aggregation/weather intervals (BLE per window, weather per hour). Grafana auto-provisioned via docker-compose.

## Development Notes

- **DB init/sync:** `storage/database.py` ensures schema and syncs `sensors` from `sensors.yaml` on startup (collector path). Treat `sensors.yaml` as the source; DB mirrors it.
- **Testing:** `test_weather.py` is self-contained (no network). Others use temp SQLite. Keep changes consistent with existing style (simple, explicit).
- **Diagnostics first:** If BLE/weather behaves oddly, check `scan.py` + logs (`journalctl -u weather-collector`) before changing aggregation logic.
- **Retention:** `RETENTION_DAYS` controls purging via `/api/cleanup` or `storage/retention.py` (0 = unlimited).
- **Dashboard behavior:** Auto mode switches to hourly rollup from 7 days onward; also supports "by windows" and "by hours" views.