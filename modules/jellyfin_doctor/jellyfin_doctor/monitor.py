"""Monitoring commands for Jellyfin logs and processes."""

from __future__ import annotations

import re
import time
from pathlib import Path

from .alerts import notify
from .logs import analyze_lines, classify_line
from .paths import resolve_log_file
from .process import find_processes
from .rendering import StatusRenderer


def monitor_scan_file(
    *,
    log_file: Path | None = None,
    log_dir: Path | None = None,
    timeout_minutes: float = 0.0,
    alert: bool = False,
    beep: bool = False,
    popup: bool = False,
) -> dict[str, object]:
    """Inspect a scan log once, optionally waiting until timeout for live use."""
    resolved = resolve_log_file(log_file, log_dir)
    if resolved is None or not resolved.exists():
        return {"status": "missing_log", "exit_code": 3, "log_file": resolved}
    deadline = time.time() + timeout_minutes * 60 if timeout_minutes > 0 else time.time()
    while True:
        lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
        summary = analyze_lines(lines)
        if summary.counts.get("scan_completed"):
            if alert:
                notify("Jellyfin scan completed", str(resolved), beep_alert=beep, popup_alert=popup)
            return {"status": "completed", "exit_code": 0, "log_file": resolved, "summary": summary.to_dict()}
        if summary.counts.get("scan_failed"):
            if alert:
                notify("Jellyfin scan failed", str(resolved), beep_alert=beep, popup_alert=popup)
            return {"status": "failed", "exit_code": 1, "log_file": resolved, "summary": summary.to_dict()}
        if time.time() >= deadline:
            return {"status": "timeout", "exit_code": 2, "log_file": resolved, "summary": summary.to_dict()}
        time.sleep(1)


def monitor_startup(
    *,
    log_file: Path | None = None,
    log_dir: Path | None = None,
    timeout_minutes: float = 5.0,
    alert: bool = False,
    beep: bool = False,
    popup: bool = False,
) -> dict[str, object]:
    """Monitor startup state in the latest log."""
    result = monitor_scan_file(log_file=log_file, log_dir=log_dir, timeout_minutes=0)
    if result["status"] == "missing_log":
        return result
    resolved = result["log_file"]
    assert isinstance(resolved, Path)
    deadline = time.time() + timeout_minutes * 60
    while True:
        summary = analyze_lines(resolved.read_text(encoding="utf-8", errors="replace").splitlines())
        if summary.counts.get("startup_ok"):
            if alert:
                notify("Jellyfin startup complete", "Open http://localhost:8096", beep_alert=beep, popup_alert=popup)
            return {"status": "startup_ok", "exit_code": 0, "log_file": resolved, "summary": summary.to_dict()}
        if summary.counts.get("fatal") or summary.counts.get("migration_missing"):
            return {"status": "startup_failed", "exit_code": 1, "log_file": resolved, "summary": summary.to_dict()}
        if time.time() >= deadline:
            return {"status": "timeout", "exit_code": 2, "log_file": resolved, "summary": summary.to_dict()}
        time.sleep(1)


def monitor_log(
    *,
    log_file: Path | None = None,
    log_dir: Path | None = None,
    pattern: str | None = None,
    ignore_case: bool = False,
    tail_lines: int = 120,
    once: bool = False,
    alert: bool = False,
    beep: bool = False,
) -> dict[str, object]:
    """Generic log tail/filter operation."""
    resolved = resolve_log_file(log_file, log_dir)
    if resolved is None or not resolved.exists():
        return {"status": "missing_log", "exit_code": 3, "log_file": resolved}
    flags = re.I if ignore_case else 0
    compiled = re.compile(pattern, flags) if pattern else None
    lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()[-tail_lines:]
    matches = [line for line in lines if compiled is None or compiled.search(line)]
    findings = [finding for line in matches for finding in classify_line(line)]
    if matches and alert:
        notify("Jellyfin log match", matches[-1], beep_alert=beep, popup_alert=False)
    return {
        "status": "matched" if matches else "no_match",
        "exit_code": 0,
        "log_file": resolved,
        "matches": matches,
        "findings": findings,
        "once": once,
    }


def monitor_processes(
    *,
    processes: list[str] | None = None,
    refresh_seconds: float = 5.0,
    in_place: bool = False,
    max_memory_gb: float | None = None,
    cpu_stall_seconds: float | None = None,
) -> dict[str, object]:
    """Sample process health once and render if requested."""
    del refresh_seconds, cpu_stall_seconds
    infos = find_processes(processes or ["jellyfin", "Jellyfin.Windows.Tray", "ffmpeg", "ffprobe"])
    status = "ok"
    warnings: list[str] = []
    if max_memory_gb is not None:
        limit = max_memory_gb * 1024 * 1024 * 1024
        for proc in infos:
            if proc.rss_bytes > limit:
                status = "warning"
                warnings.append(f"{proc.name} PID {proc.pid} exceeds {max_memory_gb:g} GB")
    with StatusRenderer(in_place=in_place, title="Jellyfin processes") as renderer:
        renderer.render({"status": status, "processes": len(infos), "warnings": "; ".join(warnings)})
    return {"status": status, "processes": infos, "warnings": warnings}
