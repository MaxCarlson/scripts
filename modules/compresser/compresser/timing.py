"""Per-image exclusive wall-time phases; nested trials never double-count."""

from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import time
from typing import Callable, Iterator

_trace = ContextVar("compression_timing", default=None)


@contextmanager
def timing_scope(callback: Callable[[str], None] | None = None) -> Iterator[dict]:
    trace = {"seconds": defaultdict(float), "stack": [], "callback": callback}
    token = _trace.set(trace)
    try:
        yield trace
    finally:
        _trace.reset(token)


@contextmanager
def phase(name: str) -> Iterator[None]:
    trace = _trace.get()
    if trace is None:
        yield
        return
    frame = [name, time.monotonic(), 0.0]
    trace["stack"].append(frame)
    if trace["callback"]:
        trace["callback"](name)
    try:
        yield
    finally:
        elapsed = max(0.0, time.monotonic() - frame[1])
        trace["seconds"][name] += max(0.0, elapsed - frame[2])
        trace["stack"].pop()
        if trace["stack"]:
            trace["stack"][-1][2] += elapsed
        if trace["callback"]:
            trace["callback"](trace["stack"][-1][0] if trace["stack"] else "finishing")


def timed(name: str) -> Callable:
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with phase(name):
                return function(*args, **kwargs)

        return wrapped

    return decorate
