#!/usr/bin/env python3
"""
Utility helpers shared across TermDash-powered dashboards.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
from pathlib import Path
from typing import List

ANSI_RESET = "\033[0m"
ANSI_CODES = {
    "default": "",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "white": "37",
    "gray": "90",
    "bright": "97",
}


def color_text(text: str, color: str | None) -> str:
    """Wrap `text` in an ANSI color code (safe for None/unknown colors)."""
    if not color:
        return text
    code = ANSI_CODES.get(color.lower())
    if not code:
        return text
    return f"\033[{code}m{text}{ANSI_RESET}"


def wrap_text(text: str, width: int) -> List[str]:
    """Wrap text to a maximum width without breaking words."""
    if width <= 0:
        return [text]
    words = str(text or "").split()
    if not words:
        return [""]
    lines: List[str] = []
    current: List[str] = []
    current_len = 0
    for word in words:
        extra = len(word) + (1 if current else 0)
        if current and (current_len + extra) > width:
            lines.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += extra
    if current:
        lines.append(" ".join(current))
    return lines or [""]


def format_bytes(mib_val):
    """Formats a numeric value in MiB into a human-readable byte string."""
    if mib_val >= 1024:
        return f"{mib_val / 1024:.2f} GiB"
    if mib_val < (1 / 1024):
        return f"{mib_val * 1024 * 1024:.2f} B"
    if mib_val < 1:
        return f"{mib_val * 1024:.2f} KiB"
    return f"{mib_val:.2f} MiB"


def format_bytes_binary(num_bytes: float | int | None) -> str:
    """Format bytes using binary units (KiB, MiB, GiB…)."""
    if num_bytes is None:
        return "0 B"
    value = float(max(0, num_bytes))
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    precision = 0 if idx == 0 else 2
    return f"{value:.{precision}f} {units[idx]}"


def format_rate_bps(num_bps: float | int | None) -> str:
    """Format bytes/sec rate with binary units."""
    if not isinstance(num_bps, (int, float)) or num_bps <= 0:
        return "0 B/s"
    value = float(num_bps)
    units = ["B/s", "KiB/s", "MiB/s", "GiB/s", "TiB/s"]
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    return f"{value:.2f} {units[idx]}"


def fmt_hms(seconds):
    """Return HH:MM:SS (accepts float or int; None -> '--:--:--')."""
    if seconds is None:
        return "--:--:--"
    s = int(max(0, float(seconds)))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def format_duration_hms(seconds: float | int | None) -> str:
    """Format seconds into H:MM:SS.mmm for higher precision displays."""
    if not isinstance(seconds, (int, float)) or seconds < 0:
        return "0:00:00.000"
    frac = float(seconds) - int(seconds)
    millis = int(frac * 1000)
    total = int(seconds)
    mins, secs = divmod(total, 60)
    hours, mins = divmod(mins, 60)
    return f"{hours:d}:{mins:02d}:{secs:02d}.{millis:03d}"


def bytes_to_mib(n_bytes):
    """Convert bytes -> mebibytes (MiB) as float."""
    try:
        return float(n_bytes) / (1024.0 * 1024.0)
    except Exception:
        return 0.0


def clip_ellipsis(text: str, max_chars: int) -> str:
    """Hard-clip string to <= max_chars, adding a single-character ellipsis if clipped."""
    if max_chars <= 0:
        return text or ""
    s = str(text or "")
    return s if len(s) <= max_chars else s[: max_chars - 1] + "."


@dataclass(frozen=True)
class DiskStats:
    """Simple snapshot of filesystem usage for a given path."""

    path: Path
    total_bytes: int
    used_bytes: int
    free_bytes: int
    device: int | None
    label: str


def _device_id(path: Path) -> int | None:
    try:
        return os.stat(path).st_dev
    except (FileNotFoundError, PermissionError):
        return None


def get_disk_stats(path: Path) -> DiskStats:
    """Return disk usage plus a human-friendly label for `path`."""
    resolved = Path(path).expanduser().resolve()
    try:
        usage = shutil.disk_usage(resolved)
    except FileNotFoundError:
        parent = resolved.parent if resolved.parent != resolved else Path(resolved.anchor or "/")
        usage = shutil.disk_usage(parent)
    label = resolved.drive or resolved.anchor or str(resolved)
    device = _device_id(resolved)
    return DiskStats(
        path=resolved,
        total_bytes=usage.total,
        used_bytes=usage.total - usage.free,
        free_bytes=usage.free,
        device=device,
        label=label.rstrip("/\\"),
    )


def same_disk(a: DiskStats, b: DiskStats) -> bool:
    """Return True if two DiskStats refer to the same underlying volume."""
    if a.device is not None and b.device is not None:
        return a.device == b.device
    # Fallback: compare labels when device IDs are unavailable (best effort)
    return a.label == b.label
