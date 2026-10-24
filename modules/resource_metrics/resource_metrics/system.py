"""Best-effort host CPU, memory, disk, and network measurements."""

from __future__ import annotations

import time
from typing import Any

import psutil


def cpu_percent(interval=None, *, per_cpu=False):
    try:
        return psutil.cpu_percent(interval=interval, percpu=per_cpu)
    except (OSError, RuntimeError):
        return None


def cpu_count(*, logical=True):
    try:
        return psutil.cpu_count(logical=logical)
    except (OSError, RuntimeError):
        return None


def memory_stats():
    try:
        memory = psutil.virtual_memory()
        return {
            "used": int(memory.used),
            "available": int(memory.available),
            "total": int(memory.total),
            "percent": float(memory.percent),
        }
    except (OSError, RuntimeError):
        return None


def disk_io_counters(*, per_disk=False):
    try:
        return psutil.disk_io_counters(perdisk=per_disk)
    except (OSError, RuntimeError):
        return None


def net_io_counters(*, per_nic=False):
    try:
        return psutil.net_io_counters(pernic=per_nic)
    except (OSError, RuntimeError):
        return None


def rate(previous, current, elapsed_seconds):
    """Return a nonnegative counter rate using monotonic elapsed seconds supplied by caller."""
    if elapsed_seconds <= 0:
        return None
    return max(0.0, float(current) - float(previous)) / elapsed_seconds


def monotonic_seconds() -> float:
    return time.monotonic()
