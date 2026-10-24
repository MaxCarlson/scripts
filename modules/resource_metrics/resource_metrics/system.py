"""Best-effort host CPU, memory, disk, and network measurements."""

from __future__ import annotations

import time
import psutil


def cpu_percent(interval=None, *, per_cpu=False):
    try:
        return psutil.cpu_percent(interval=interval, percpu=per_cpu)
    except (psutil.Error, OSError, RuntimeError):
        return None


def cpu_count(*, logical=True):
    try:
        return psutil.cpu_count(logical=logical)
    except (psutil.Error, OSError, RuntimeError):
        return None


def memory_stats():
    try:
        memory = psutil.virtual_memory()
        used = getattr(memory, "used", None)
        total = getattr(memory, "total", None)
        return {"used": int(used) if used is not None else None,
                "available": int(memory.available),
                "total": int(total) if total is not None else None,
                "percent": float(memory.percent)}
    except (psutil.Error, OSError, RuntimeError):
        return None


def disk_io_counters(*, per_disk=False):
    try:
        return psutil.disk_io_counters(perdisk=per_disk)
    except (psutil.Error, OSError, RuntimeError):
        return None


def net_io_counters(*, per_nic=False):
    try:
        return psutil.net_io_counters(pernic=per_nic)
    except (psutil.Error, OSError, RuntimeError):
        return None


def rate(previous, current, elapsed_seconds):
    """Return a nonnegative counter rate for an elapsed monotonic interval."""
    if elapsed_seconds <= 0:
        return None
    return max(0.0, float(current) - float(previous)) / elapsed_seconds


def monotonic_seconds():
    return time.monotonic()
