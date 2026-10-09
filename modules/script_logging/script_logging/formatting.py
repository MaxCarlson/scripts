"""Composable text formatting and standard-library logging adapters."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Optional

from .store import EventRecord, HistoryStore

DEFAULT_FIELDS = ("date", "time", "level", "source", "message")
COLORS = {
    "DEBUG": "\x1b[36m",
    "INFO": "\x1b[32m",
    "WARNING": "\x1b[33m",
    "ERROR": "\x1b[31m",
    "CRITICAL": "\x1b[91m",
}


class EventFormatter(logging.Formatter):
    """Render chosen fields in chosen order, with optional ANSI level colors."""

    def __init__(
        self, fields: Iterable[str] = DEFAULT_FIELDS, *, separator: str = " | ",
        colors: bool = False, date_format: str = "%Y-%m-%d", time_format: str = "%H:%M:%S",
        color_map: Optional[Mapping[str, str]] = None,
    ) -> None:
        super().__init__()
        self.fields = tuple(fields)
        allowed = {"date", "time", "level", "type", "source", "name", "message"}
        unknown = set(self.fields) - allowed
        if unknown:
            raise ValueError(f"Unknown log fields: {', '.join(sorted(unknown))}")
        self.separator = separator
        self.colors = colors
        self.date_format = date_format
        self.time_format = time_format
        self.color_map = dict(color_map) if color_map is not None else COLORS

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).astimezone()
        level = record.levelname.upper()
        parts = {
            "date": timestamp.strftime(self.date_format),
            "time": timestamp.strftime(self.time_format),
            "level": level,
            "type": str(getattr(record, "event_type", level)),
            "source": record.name,
            "name": record.name,
            "message": record.getMessage(),
        }
        rendered = self.separator.join(parts[field] for field in self.fields)
        if record.exc_info:
            rendered += "\n" + self.formatException(record.exc_info)
        prefix = self.color_map.get(level, "") if self.colors else ""
        return f"{prefix}{rendered}\x1b[0m" if prefix else rendered


def text_file_handler(path: Path, *, fields: Iterable[str] = DEFAULT_FIELDS) -> logging.FileHandler:
    """Return a file handler with configurable plain-text fields and no ANSI escapes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(EventFormatter(fields=fields, colors=False))
    return handler


class StoreHandler(logging.Handler):
    """Send stdlib logging records into a generic HistoryStore."""

    def __init__(self, store: HistoryStore, *, source: str, entity_type: str = "", entity_id: str = "") -> None:
        super().__init__()
        self.store = store
        self.source = source
        self.entity_type = entity_type
        self.entity_id = entity_id

    def emit(self, record: logging.LogRecord) -> None:
        try:
            occurred_at = datetime.fromtimestamp(record.created).astimezone().isoformat()
            self.store.append_event(
                EventRecord(
                    source=self.source, event_type=str(getattr(record, "event_type", record.levelname)),
                    occurred_at=occurred_at, message=record.getMessage(),
                    entity_type=self.entity_type, entity_id=self.entity_id, level=record.levelname,
                )
            )
        except (OSError, ValueError, sqlite3.Error):
            self.handleError(record)
