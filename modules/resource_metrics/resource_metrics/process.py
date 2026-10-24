"""Best-effort process measurements and process-tree enumeration."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

import psutil


def process_tree(pid: int, *, psutil_module: Any = psutil) -> list[Any]:
    try:
        root = psutil_module.Process(pid)
        return [root, *root.children(recursive=True)]
    except psutil_module.Error:
        return []


def process_tree_snapshot(pid: int) -> dict[str, int | float] | None:
    """Aggregate current RSS, thread count, and raw CPU percent for a process tree."""
    processes = process_tree(pid)
    if not processes:
        return None
    cpu = rss = threads = 0
    for process in processes:
        try:
            cpu += float(process.cpu_percent(interval=None))
            rss += int(process.memory_info().rss)
            threads += int(process.num_threads())
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return {"pid": pid, "cpu_percent": cpu, "rss_bytes": rss, "threads": threads,
            "children": max(0, len(processes) - 1)}


def process_io(process: psutil.Process) -> Any | None:
    with suppress(psutil.Error, AttributeError, OSError):
        return process.io_counters()
    return None


def top_process_memory(limit: int = 8) -> list[dict[str, int | str]]:
    """Return the largest resident processes without command-line details."""
    rows: list[dict[str, int | str]] = []
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
