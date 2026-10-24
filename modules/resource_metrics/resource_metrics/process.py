"""Best-effort process measurements and process-tree enumeration."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

import psutil


def process_tree(pid: int, *, psutil_module: Any = psutil) -> list[Any]:
    """Return the root process and live descendant processes.

    Safely handles permission denials, missing processes, zombies, and process exit
    during tree traversal.
    """
    if pid is None or pid <= 0:
        return []
    try:
        root = psutil_module.Process(pid)
        if hasattr(root, "is_running") and not root.is_running():
            return []
    except (psutil_module.Error, OSError, ValueError):
        return []

    try:
        children = root.children(recursive=True)
    except (psutil_module.Error, OSError):
        return [root]

    live = [root]
    for child in children:
        with suppress(psutil_module.Error, OSError):
            if not hasattr(child, "is_running") or child.is_running():
                live.append(child)
    return live


def process_tree_snapshot(
    pid: int,
    *,
    psutil_module: Any = psutil,
    previous_cpu_time_seconds: Any = None,
    elapsed_seconds: Any = None,
    logical_cpu_count: int | None = None,
) -> dict[str, Any] | None:
    """Aggregate a process tree; CPU percent is unavailable until given a valid prior sample.

    Calculates:
    - cpu_percent: raw multi-core percentage (100% per core)
    - cpu_percent_normalized: normalized percentage against logical CPU count (0-100%)
    - rss_bytes: total resident set size across living tree
    - threads: total thread count
    - read_bytes / write_bytes: total I/O bytes if supported on the host platform
    """
    processes = process_tree(pid, psutil_module=psutil_module)
    if not processes:
        return None

    cpu_time = 0.0
    rss = 0
    threads = 0
    total_read_bytes = 0
    total_write_bytes = 0
    io_supported = False
    root_create_time = None

    for index, process in enumerate(processes):
        try:
            times = process.cpu_times()
            cpu_time += float(times.user) + float(times.system)
            rss += int(process.memory_info().rss)
            threads += int(process.num_threads())
            if index == 0 and hasattr(process, "create_time"):
                root_create_time = float(process.create_time())
        except (psutil_module.Error, OSError):
            continue

        counters = process_io(process, psutil_module=psutil_module)
        if counters is not None:
            read_val = getattr(counters, "read_bytes", None)
            write_val = getattr(counters, "write_bytes", None)
            if read_val is not None:
                total_read_bytes += int(read_val)
                io_supported = True
            if write_val is not None:
                total_write_bytes += int(write_val)
                io_supported = True

    cpu_percent = None
    if previous_cpu_time_seconds is not None and elapsed_seconds is not None and elapsed_seconds > 0:
        cpu_percent = max(0.0, (cpu_time - float(previous_cpu_time_seconds)) / elapsed_seconds * 100.0)

    cores = logical_cpu_count
    if cores is None:
        try:
            cores = psutil_module.cpu_count(logical=True)
        except (psutil_module.Error, OSError, AttributeError):
            cores = None
    cores = max(1, int(cores or 1))

    cpu_percent_normalized = (cpu_percent / cores) if cpu_percent is not None else None

    return {
        "pid": pid,
        "cpu_percent": cpu_percent,
        "cpu_percent_normalized": cpu_percent_normalized,
        "cpu_count": cores,
        "cpu_time_seconds": cpu_time,
        "rss_bytes": rss,
        "threads": threads,
        "children": max(0, len(processes) - 1),
        "process_count": len(processes),
        "read_bytes": total_read_bytes if io_supported else None,
        "write_bytes": total_write_bytes if io_supported else None,
        "io_supported": io_supported,
        "create_time": root_create_time,
    }


def process_io(process: Any, *, psutil_module: Any = psutil) -> Any:
    """Safely return process I/O counters or None if unsupported or inaccessible."""
    with suppress(psutil_module.Error, AttributeError, OSError, NotImplementedError):
        return process.io_counters()
    return None


def top_process_memory(limit: int = 8) -> list[dict[str, Any]]:
    """Return the largest resident processes without command-line details."""
    rows: list[dict[str, Any]] = []
    try:
        processes = psutil.process_iter(["pid", "name", "memory_info"], ad_value=None)
        for process in processes:
            try:
                info = process.info
                memory = info.get("memory_info")
                if memory is not None:
                    rows.append(
                        {
                            "pid": int(info["pid"]),
                            "name": info.get("name") or "unknown",
                            "rss_bytes": int(memory.rss),
                        }
                    )
            except (psutil.Error, OSError):
                continue
    except (psutil.Error, OSError):
        return []
    return sorted(rows, key=lambda row: int(row["rss_bytes"]), reverse=True)[: max(0, limit)]
