"""Политика ретеншна (удаление старых показаний).

RETENTION_DAYS > 0 → удаляет readings старше указанного количества дней.
RETENTION_DAYS = 0 → очистка отключена.

Запускается периодическим фоновым task в коллекторе
и по запросу через API-эндпоинт POST /api/cleanup.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from storage.database import get_session
from storage.models import Reading

logger = logging.getLogger(__name__)


def cleanup_old_readings(days: int) -> int:
    """Удаляет показания старше ``days`` дней.

    Returns:
        Количество удалённых записей.
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    with get_session() as session:
        stmt = delete(Reading).where(Reading.recorded_at < cutoff)
        result = session.execute(stmt)
        deleted = result.rowcount

    if deleted:
        logger.info("Retention: deleted %d readings older than %s", deleted, cutoff)
    return deleted


def count_old_readings(days: int) -> int:
    """Возвращает количество записей, которые будут удалены."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    with get_session() as session:
        stmt = select(Reading.id).where(Reading.recorded_at < cutoff)
        return len(session.execute(stmt).all())
