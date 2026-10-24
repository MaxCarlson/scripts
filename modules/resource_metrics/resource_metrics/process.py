"""Best-effort process measurements and process-tree enumeration."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

import psutil


def process_tree(pid: int, *, psutil_module: Any = psutil) -> list[Any]:
    try:
        root = psutil_module.Process(pid)
    except psutil_module.Error:
        return []
    try:
        return [root, *root.children(recursive=True)]
    except psutil_module.Error:
        return [root]


def process_tree_snapshot(pid: int, *, psutil_module: Any = psutil,
                          previous_cpu_time_seconds: Any = None, elapsed_seconds: Any = None) -> Any:
    """Aggregate a process tree; CPU percent is unavailable until given a valid prior sample."""
    processes = process_tree(pid, psutil_module=psutil_module)
    if not processes:
        return None
    cpu_time = rss = threads = 0
    for process in processes:
        try:
            times = process.cpu_times()
            cpu_time += float(times.user) + float(times.system)
            rss += int(process.memory_info().rss)
            threads += int(process.num_threads())
        except psutil_module.Error:
            continue
    cpu_percent = None
    if previous_cpu_time_seconds is not None and elapsed_seconds is not None and elapsed_seconds > 0:
        cpu_percent = max(0.0, (cpu_time - float(previous_cpu_time_seconds)) / elapsed_seconds * 100.0)
    return {"pid": pid, "cpu_percent": cpu_percent, "cpu_time_seconds": cpu_time,
            "rss_bytes": rss, "threads": threads, "children": max(0, len(processes) - 1)}


def process_io(process, *, psutil_module: Any = psutil):
    with suppress(psutil_module.Error, AttributeError, OSError):
        return process.io_counters()
    return None


def top_process_memory(limit: int = 8):
    """Return the largest resident processes without command-line details."""
    rows: list[dict[str, Any]] = []
    try:
        processes = psutil.process_iter(["pid", "name", "memory_info"], ad_value=None)
        for process in processes:
            try:
                info = process.info
                memory = info.get("memory_info")
                if memory is not None:
                    rows.append({"pid": int(info["pid"]), "name": info.get("name") or "unknown",
                                 "rss_bytes": int(memory.rss)})
            except (psutil.Error, OSError):
                continue
    except (psutil.Error, OSError):
        return []
    return sorted(rows, key=lambda row: int(row["rss_bytes"]), reverse=True)[:max(0, limit)]
