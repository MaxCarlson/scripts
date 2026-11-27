"""Noninteractive Rich, JSON, and CSV snapshot exporters for process_watch."""

from __future__ import annotations

import csv
import io
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from rich.console import Console
from rich.table import Table

from .filters import COLUMN_DEFS, COLUMN_PRESETS
from .models import (
    MonitoringSnapshot,
    ProcessSample,
    format_bytes_iec,
    format_duration,
    format_percent,
    format_rate_iec,
)


def format_cell_value(sample: ProcessSample, col_key: str, *, aggregated: bool = False) -> str:
    """Format one table cell consistently using IEC units and '-' for unavailable metrics."""
    if col_key == "pid":
        return str(sample.pid)
    if col_key == "ppid":
        return str(sample.ppid)
    if col_key == "name":
        prefix = ""
        if sample.is_exited:
            prefix = "[EXITED] "
        elif sample.is_new:
            prefix = "[NEW] "
        return f"{prefix}{sample.name}"
    if col_key == "status":
        return "exited" if sample.is_exited else (sample.status or "-")
    if col_key == "user":
        return sample.username or "-"
    if col_key == "exe":
        return sample.exe or "-"
    if col_key == "cpu":
        val = sample.subtree_cpu_percent if aggregated else sample.cpu_percent
        return format_percent(val)
    if col_key == "cpu_norm":
        return format_percent(sample.cpu_percent_normalized)
    if col_key == "rss":
        val = sample.subtree_rss_bytes if aggregated else sample.rss_bytes
        return format_bytes_iec(val)
    if col_key == "private_mem":
        return format_bytes_iec(sample.private_bytes)
    if col_key == "vms":
        return format_bytes_iec(sample.vms_bytes)
    if col_key == "io_read":
        val = sample.subtree_io_read_rate if aggregated else sample.io_read_rate
        return format_rate_iec(val)
    if col_key == "io_write":
        val = sample.subtree_io_write_rate if aggregated else sample.io_write_rate
        return format_rate_iec(val)
    if col_key == "io_total":
        if aggregated:
            r = sample.subtree_io_read_rate
            w = sample.subtree_io_write_rate
            val = None if (r is None and w is None) else (r or 0.0) + (w or 0.0)
        else:
            val = sample.io_total_rate
        return format_rate_iec(val)
    if col_key == "gpu_mem":
        return format_bytes_iec(sample.gpu_memory_bytes)
    if col_key == "gpu_id":
        return str(sample.gpu_id) if sample.gpu_id is not None else "-"
    if col_key == "gpu_util":
        return format_percent(sample.gpu_util_percent)
    if col_key == "threads":
        return str(sample.num_threads) if sample.num_threads is not None else "-"
    if col_key == "handles":
        return str(sample.num_handles) if sample.num_handles is not None else "-"
    if col_key == "peak_cpu":
        return format_percent(sample.peak_cpu_percent)
    if col_key == "peak_rss":
        return format_bytes_iec(sample.peak_rss_bytes)
    if col_key == "subtree_cpu":
        return format_percent(sample.subtree_cpu_percent)
    if col_key == "subtree_rss":
        return format_bytes_iec(sample.subtree_rss_bytes)
    if col_key == "uptime":
        return format_duration(sample.uptime_seconds)
    return "-"


def build_export_payload(
    snapshot: MonitoringSnapshot,
    rows: Sequence[ProcessSample],
    *,
    aggregated: bool = False,
) -> Dict[str, Any]:
    """Build structured JSON export payload with units, platform, and GPU provenance."""
    ts_iso = datetime.fromtimestamp(snapshot.sampled_at_epoch, tz=timezone.utc).isoformat()
    return {
        "timestamp_utc": ts_iso,
        "platform": platform.platform(),
        "measurement_scope": "subtree_aggregate" if aggregated else "process",
        "units": {
            "cpu_percent": "percent (100% per logical core)",
            "cpu_percent_normalized": "percent (0-100% of host)",
            "memory": "bytes",
            "io_rate": "bytes/second (process I/O counters, not physical disk)",
        },
        "host": {
            "cpu_percent": snapshot.host.cpu_percent,
            "cpu_count": snapshot.host.cpu_count,
            "mem_used_bytes": snapshot.host.mem_used_bytes,
            "mem_total_bytes": snapshot.host.mem_total_bytes,
            "disk_read_bytes_per_sec": snapshot.host.disk_read_rate,
            "disk_write_bytes_per_sec": snapshot.host.disk_write_rate,
            "gpu_backend": snapshot.host.gpu_backend,
            "gpu_age_seconds": snapshot.host.gpu_age_seconds,
            "gpu_limitations": snapshot.host.gpu_limitations,
            "gpu_devices": snapshot.host.gpu_devices,
            "total_processes": snapshot.host.total_processes,
            "matched_processes": len(rows),
        },
        "processes": [row.to_export_dict(aggregated=aggregated) for row in rows],
    }


def render_json(
    snapshot: MonitoringSnapshot,
    rows: Sequence[ProcessSample],
    *,
    aggregated: bool = False,
) -> str:
    return json.dumps(build_export_payload(snapshot, rows, aggregated=aggregated), indent=2)


def render_csv(
    rows: Sequence[ProcessSample],
    *,
    aggregated: bool = False,
) -> str:
    buf = io.StringIO()
    dicts = [row.to_export_dict(aggregated=aggregated) for row in rows]
    fieldnames = (
        list(dicts[0].keys())
        if dicts
        else [
            "pid",
            "ppid",
            "create_time",
            "identity_key",
            "name",
            "status",
            "measurement_scope",
            "cpu_percent",
            "rss_bytes",
            "io_read_bytes_per_sec",
            "io_write_bytes_per_sec",
            "gpu_memory_bytes",
        ]
    )
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in dicts:
        writer.writerow(row)
    return buf.getvalue()


def render_rich_table(
    snapshot: MonitoringSnapshot,
    rows: Sequence[ProcessSample],
    *,
    columns: Optional[Sequence[str]] = None,
    aggregated: bool = False,
    limit: Optional[int] = None,
    console: Optional[Console] = None,
) -> str:
    """Render a static Rich table for one-shot or non-TTY output."""
    cols = list(columns or COLUMN_PRESETS["default"])
    visible = list(rows[:limit]) if limit is not None and limit > 0 else list(rows)
    scope_label = "Subtree Aggregate" if aggregated else "Individual Process"
    title = (
        f"proc-stats ({scope_label}) | Host CPU: {snapshot.host.cpu_percent:.1f}% | "
        f"RAM: {format_bytes_iec(snapshot.host.mem_used_bytes)}/{format_bytes_iec(snapshot.host.mem_total_bytes)} | "
        f"Showing {len(visible)}/{len(rows)}"
    )
    table = Table(title=title, expand=False)
    for key in cols:
        header, right = COLUMN_DEFS.get(key, (key, False))
        if aggregated and key in ("cpu", "rss", "io_read", "io_write", "io_total"):
            header = f"Tree {header}"
        table.add_column(header, justify="right" if right else "left")

    for sample in visible:
        table.add_row(*[format_cell_value(sample, key, aggregated=aggregated) for key in cols])

    if console is not None:
        console.print(table)
        return ""
    capture = Console(record=True, width=140)
    capture.print(table)
    return capture.export_text()


def write_export_file(path: Path, content: str, *, force: bool = False) -> None:
    """Write export content to explicit destination, requiring force=True to overwrite."""
    if path.exists() and not force:
        raise FileExistsError(f"Output file already exists: {path}. Pass --force to overwrite.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
