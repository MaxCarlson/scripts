"""Utilities for capturing and querying server logs at runtime."""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Deque, Dict, List, Optional

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class LogBufferHandler(logging.Handler):
    """Ring buffer handler that keeps recent log records in memory."""

    def __init__(self, capacity: int = 4000):
        super().__init__(logging.DEBUG)
        self.capacity = capacity
        self._buffer: Deque[Dict[str, object]] = deque(maxlen=capacity)
        self._lock = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "levelno": record.levelno,
                "logger": record.name,
                "message": record.getMessage(),
                "pathname": record.pathname,
                "lineno": record.lineno,
                "process": record.process,
                "thread": record.threadName,
                "is_access": record.name.startswith("uvicorn.access"),
            }
        except Exception:
            self.handleError(record)
            return

        with self._lock:
            self._buffer.append(entry)

    def get_logs(
        self,
        limit: int = 200,
        min_level: Optional[int] = None,
        include_access: bool = False,
    ) -> List[Dict[str, object]]:
        with self._lock:
            items = list(self._buffer)

        result: List[Dict[str, object]] = []
        for entry in reversed(items):
            if not include_access and entry.get("is_access"):
                continue
            if min_level is not None and int(entry.get("levelno", 0)) < min_level:
                continue
            result.append(entry)
            if len(result) >= limit:
                break

        result.reverse()
        return result

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()


_LOG_HANDLER = LogBufferHandler()


def install_log_buffer() -> LogBufferHandler:
    """Attach the log buffer handler to the root logger if needed."""
    root_logger = logging.getLogger()
    if _LOG_HANDLER not in root_logger.handlers:
        root_logger.addHandler(_LOG_HANDLER)
    return _LOG_HANDLER


def get_recent_logs(limit: int = 200, min_level_name: str = "INFO", include_access: bool = False):
    """Return serialized recent log entries."""
    numeric_level = None
    if min_level_name:
        level_name = min_level_name.upper()
        numeric_level = logging.getLevelName(level_name)
        if isinstance(numeric_level, str):
            numeric_level = logging.INFO
    return _LOG_HANDLER.get_logs(limit=limit, min_level=numeric_level, include_access=include_access)


def list_logger_levels() -> List[Dict[str, str]]:
    """Expose the effective levels for common loggers."""
    logger_names = {
        "root",
        "orchestrator_web_viewer",
        "orchestrator_web_viewer.api",
        "orchestrator_web_viewer.websocket",
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
    }
    logger_names.update(
        name
        for name, value in logging.Logger.manager.loggerDict.items()
        if isinstance(value, logging.Logger) and name.startswith("orchestrator_web_viewer")
    )

    levels = []
    for name in sorted(logger_names):
        logger = logging.getLogger(None if name == "root" else name)
        levels.append(
            {
                "name": name,
                "level": logging.getLevelName(logger.getEffectiveLevel()),
            }
        )
    return levels


def update_logger_level(logger_name: str, level_name: str) -> Dict[str, str]:
    """Update logging level for the requested logger."""
    target_name = logger_name or "root"
    level = logging.getLevelName(level_name.upper())
    if isinstance(level, str):
        raise ValueError(f"Unknown log level: {level_name}")
    logger = logging.getLogger(None if target_name == "root" else target_name)
    logger.setLevel(level)
    return {"name": target_name, "level": logging.getLevelName(logger.getEffectiveLevel())}
