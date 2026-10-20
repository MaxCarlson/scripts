"""Configure experiment-scoped diagnostics using the repository's shared logger."""

from __future__ import annotations

import logging
from pathlib import Path

from script_logging import text_file_handler

_LOGGER_NAMES = ("agent_benchmark", "benchmark_core")
_HANDLER_MARKER = "_agent_benchmark_run_handler"


def configure_run_logging(path: Path) -> logging.Handler:
    """Attach one plain UTF-8 file handler to benchmark runtime namespaces."""
    for name in _LOGGER_NAMES:
        logger = logging.getLogger(name)
        for existing in tuple(logger.handlers):
            if getattr(existing, _HANDLER_MARKER, False):
                logger.removeHandler(existing)
                existing.close()

    handler = text_file_handler(path, fields=("date", "time", "level", "type", "source", "message"))
    setattr(handler, _HANDLER_MARKER, True)
    handler.setLevel(logging.INFO)
    for name in _LOGGER_NAMES:
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.propagate = False
    return handler


def close_run_logging(handler: logging.Handler) -> None:
    """Detach and close the experiment handler without changing root logging."""
    for name in _LOGGER_NAMES:
        logging.getLogger(name).removeHandler(handler)
    handler.close()
