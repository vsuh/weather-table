"""Настройка логирования: текстовый или JSON формат.

Используется и коллектором, и API, чтобы формат логов совпадал.

LOG_FORMAT=text → человекочитаемый (по умолчанию).
LOG_FORMAT=json → по одной JSON-строке на событие (удобно для journal/systemd,
                  Loki, Grafana и любого сборщика логов).
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Optional

import config


_TEXT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


class _JsonFormatter(logging.Formatter):
    """Формирует по одной JSON-строке на запись лога."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Если логируем через logger.exception(...), добавляем traceback.
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(
    level: Optional[str] = None,
    fmt: Optional[str] = None,
    stream=None,
) -> None:
    """Настраивает корневой логгер.

    Args:
        level: уровень (по умолчанию config.LOG_LEVEL).
        fmt: 'text' | 'json' (по умолчанию config.LOG_FORMAT).
        stream: поток вывода (по умолчанию sys.stdout).
    """
    level = (level or config.LOG_LEVEL).upper()
    fmt = (fmt or config.LOG_FORMAT).lower()

    handler = logging.StreamHandler(stream or sys.stdout)
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_TEXT_FORMAT))

    root = logging.getLogger()
    # Убираем ранее добавленные обработчики, чтобы не дублировать вывод.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.INFO))

    # uvicorn ставит свои обработчики — их тоже уводим в json при необходимости.
    if fmt == "json":
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            named = logging.getLogger(name)
            for existing in list(named.handlers):
                named.removeHandler(existing)
            named.addHandler(handler)
            named.propagate = False
