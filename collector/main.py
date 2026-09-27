"""Точка входа для сервиса сбора данных."""

import asyncio
import logging
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path, чтобы импортировать модули верхнего уровня
# (logging_utils, config) при запуске из collector/main.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from logging_utils import setup_logging

import config
from storage.database import init_db, sync_sensors
from storage.retention import cleanup_old_readings
from collector.registry import load_registry
from collector.aggregator import run_collector

logger = logging.getLogger(__name__)


async def _retention_loop() -> None:
    """Периодически удаляет старые показания."""
    if config.RETENTION_DAYS <= 0:
        logger.info("Retention disabled (RETENTION_DAYS=0)")
        return

    logger.info("Retention enabled: %d days", config.RETENTION_DAYS)

    while True:
        try:
            await asyncio.sleep(config.RETENTION_CHECK_INTERVAL)
            deleted = cleanup_old_readings(config.RETENTION_DAYS)
            logger.info("Retention check: deleted %d old records", deleted)
        except Exception:
            logger.exception("Retention check failed")


async def main() -> None:
    setup_logging()
    logger.info("Weather data collector starting...")

    registry = load_registry()
    if not registry.sensors:
        logger.error("No sensors configured in %s", config.SENSORS_FILE)
        return

    init_db()
    sync_sensors(registry)

    retention_task = asyncio.create_task(_retention_loop())

    try:
        await run_collector(registry)
    finally:
        retention_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
