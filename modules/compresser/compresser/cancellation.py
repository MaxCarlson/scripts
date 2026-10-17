"""Cooperative cancellation between native encoder calls."""

from contextlib import contextmanager
from contextvars import ContextVar
from concurrent.futures import CancelledError

_event = ContextVar("compression_cancellation", default=None)


@contextmanager
def cancellation_scope(event):
    token = _event.set(event)
    try:
        yield
    finally:
        _event.reset(token)


def check_cancelled():
    event = _event.get()
    if event is not None and event.is_set():
        raise CancelledError("Compression cancelled")
