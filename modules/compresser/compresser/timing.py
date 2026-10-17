"""Per-image exclusive wall-time phases; nested trials never double-count."""

from collections import Counter, defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import time
import platform
import threading
from typing import Callable, Iterable, Iterator

from PIL import __version__ as pillow_version

_trace = ContextVar("compression_timing", default=None)
_pipeline = ContextVar("compression_pipeline", default=None)
_role = ContextVar("compression_execution_role", default="coordinator")


class PipelineDiagnostics:
    """Thread-safe current-run evidence, separate from persisted result timings."""

    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.cpu_started = time.process_time()
        self._lock = threading.RLock()
        self._seconds = {"coordinator": defaultdict(float), "worker": defaultdict(float)}
        self._counters = Counter()
        self._settings = {}

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] += value

    def observe_max(self, name: str, value: int) -> None:
        with self._lock:
            self._counters[name] = max(self._counters[name], value)

    def configure(self, **settings) -> None:
        with self._lock:
            self._settings.update(settings)

    def record(self, role: str, seconds: dict) -> None:
        with self._lock:
            for name, value in seconds.items():
                self._seconds[role][name] += value

    def report(self) -> dict:
        with self._lock:
            return {
                "wall_seconds": max(0.0, time.perf_counter() - self.started),
                "process_cpu_seconds": max(0.0, time.process_time() - self.cpu_started),
                "coordinator_seconds": dict(self._seconds["coordinator"]),
                "worker_seconds": dict(self._seconds["worker"]),
                "counters": dict(self._counters),
                "settings": dict(self._settings),
                "environment": {
                    "python": platform.python_version(),
                    "platform": platform.system(),
                    "pillow": pillow_version,
                },
                "timing_scope": "current run exclusive measured phases; worker seconds add across threads; "
                "elapsed captured when report is constructed, before final output/cleanup; "
                "uninstrumented overhead remains; cache hits never replay old encoder timings",
            }


def current_pipeline() -> PipelineDiagnostics | None:
    return _pipeline.get()


def pipeline_report() -> dict:
    metrics = current_pipeline()
    return metrics.report() if metrics is not None else {}


def increment(name: str, value: int = 1) -> None:
    metrics = current_pipeline()
    if metrics is not None:
        metrics.increment(name, value)


def configure_pipeline(**settings) -> None:
    metrics = current_pipeline()
    if metrics is not None:
        metrics.configure(**settings)


@contextmanager
def pipeline_scope() -> Iterator[PipelineDiagnostics]:
    metrics = PipelineDiagnostics()
    token = _pipeline.set(metrics)
    try:
        yield metrics
    finally:
        _pipeline.reset(token)


@contextmanager
def execution_role(role: str) -> Iterator[None]:
    if role not in ("coordinator", "worker"):
        raise ValueError("Unknown pipeline execution role")
    previous_role = _role.get()
    token = _role.set(role)
    trace_token = _trace.set(None) if role != previous_role else None
    try:
        yield
    finally:
        if trace_token is not None:
            _trace.reset(trace_token)
        _role.reset(token)


def profile_pipeline(function: Callable) -> Callable:
    @wraps(function)
    def wrapped(*args, **kwargs):
        with pipeline_scope():
            return function(*args, **kwargs)

    return wrapped


@contextmanager
def timing_scope(callback: Callable[[str], None] | None = None) -> Iterator[dict]:
    parent = _trace.get()
    started = time.perf_counter()
    trace = {"seconds": defaultdict(float), "stack": [], "callback": callback}
    token = _trace.set(trace)
    try:
        yield trace
    finally:
        _trace.reset(token)
        # Separate traces (e.g. cache probes inside preparation) remain exclusive.
        if parent is not None and parent["stack"]:
            parent["stack"][-1][2] += max(0.0, time.perf_counter() - started)
        metrics = current_pipeline()
        if metrics is not None:
            metrics.record(_role.get(), trace["seconds"])


@contextmanager
def phase(name: str) -> Iterator[None]:
    trace = _trace.get()
    if trace is None:
        if current_pipeline() is None:
            yield
        else:
            with timing_scope(), phase(name):
                yield
        return
    frame = [name, time.perf_counter(), 0.0]
    trace["stack"].append(frame)
    if trace["callback"]:
        trace["callback"](name)
    try:
        yield
    finally:
        elapsed = max(0.0, time.perf_counter() - frame[1])
        trace["seconds"][name] += max(0.0, elapsed - frame[2])
        trace["stack"].pop()
        if trace["stack"]:
            trace["stack"][-1][2] += elapsed
        if trace["callback"]:
            trace["callback"](trace["stack"][-1][0] if trace["stack"] else "finishing")


def phase_iter(iterable: Iterable, name: str) -> Iterator:
    """Measure iterator advancement, not time spent processing yielded items."""
    iterator = iter(iterable)
    while True:
        with phase(name):
            try:
                item = next(iterator)
            except StopIteration:
                return
        yield item


def timed(name: str) -> Callable:
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with phase(name):
                return function(*args, **kwargs)

        return wrapped

    return decorate
