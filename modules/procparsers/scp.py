#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scp parser for progress output.

SCP provides limited progress info compared to rsync/rclone.

Example progress line (with -v):
  file.txt                                         12%  1234KB  12.3KB/s   00:23 ETA

Note: SCP's progress output is minimal. For better progress tracking,
consider using rsync with -e ssh instead of plain SCP.

Returns normalized event dicts:
  - {'event':'progress', 'percent':..., 'downloaded':..., 'speed_bps':..., 'eta_s':...}
  - {'event':'file', 'path':...}
"""
from __future__ import annotations

import re
from typing import Dict, Optional

from .utils import sanitize_line

# SCP progress line pattern
# Format: "filename    12%  1234KB  12.3KB/s   00:23 ETA" or with HH:MM:SS
_PROGRESS_RE = re.compile(
    r"(?P<filename>\S+.*?)\s+"
    r"(?P<pct>\d+)%\s+"
    r"(?P<size>[\d.]+)(?P<size_unit>[KMG]?B)\s+"
    r"(?P<speed>[\d.]+)(?P<speed_unit>[KMG]?B)/s\s+"
    r"(?P<eta>\d+:\d+(?::\d+)?)",  # Supports both MM:SS and HH:MM:SS
    re.I
)

# Alternative simpler pattern (some SCP versions)
# Format: "file.txt  100%  1234KB  12.3KB/s"
_SIMPLE_PROGRESS_RE = re.compile(
    r"(?P<filename>\S+.*?)\s+"
    r"(?P<pct>\d+)%\s+"
    r"(?P<size>[\d.]+)(?P<size_unit>[KMG]?B)\s+"
    r"(?P<speed>[\d.]+)(?P<speed_unit>[KMG]?B)/s",
    re.I
)

# File start line (verbose mode)
_FILE_START_RE = re.compile(
    r"Sending\s+file\s+.*?:\s*(?P<path>.+)",
    re.I
)

# Size multipliers
_SIZE_UNITS = {
    "B": 1,
    "KB": 1024,
    "MB": 1024 ** 2,
    "GB": 1024 ** 3,
    "TB": 1024 ** 4,
}


def _parse_size(value: float, unit: str) -> int:
    """Convert size value with unit to bytes."""
    unit_upper = unit.upper()
    mult = _SIZE_UNITS.get(unit_upper, 1)
    return int(value * mult)


def _parse_eta(eta_str: str) -> Optional[int]:
    """
    Parse ETA string 'MM:SS' -> seconds.
    """
    try:
        parts = eta_str.split(":")
        if len(parts) == 2:
            m, s = map(int, parts)
            return m * 60 + s
        elif len(parts) == 3:
            h, m, s = map(int, parts)
            return h * 3600 + m * 60 + s
    except (ValueError, AttributeError):
        pass
    return None


def parse_line(line: str) -> Optional[Dict]:
    """
    Parse a single SCP output line into a normalized dict (or None if not relevant).

    Returns one of:
      - {'event':'progress', 'percent', 'downloaded', 'speed_bps', 'eta_s', 'current_file'}
      - {'event':'file', 'path'}

    Note: SCP doesn't provide total transfer size for multi-file operations,
    so 'total' will typically be None.
    """
    s = sanitize_line(line)

    if not s:
        return None

    # Try full progress line with ETA
    m = _PROGRESS_RE.match(s)
    if m:
        filename = m.group("filename").strip()
        percent = float(m.group("pct"))
        size = float(m.group("size"))
        size_unit = m.group("size_unit")
        speed = float(m.group("speed"))
        speed_unit = m.group("speed_unit")
        eta_str = m.group("eta")

        downloaded_bytes = _parse_size(size, size_unit)
        speed_bps = _parse_size(speed, speed_unit)
        eta_s = _parse_eta(eta_str)

        return {
            "event": "progress",
            "percent": percent,
            "downloaded": downloaded_bytes,
            "total": None,  # SCP doesn't report total for multi-file
            "speed_bps": speed_bps,
            "eta_s": eta_s,
            "current_file": filename,
        }

    # Try simpler progress line without ETA
    m = _SIMPLE_PROGRESS_RE.match(s)
    if m:
        filename = m.group("filename").strip()
        percent = float(m.group("pct"))
        size = float(m.group("size"))
        size_unit = m.group("size_unit")
        speed = float(m.group("speed"))
        speed_unit = m.group("speed_unit")

        downloaded_bytes = _parse_size(size, size_unit)
        speed_bps = _parse_size(speed, speed_unit)

        return {
            "event": "progress",
            "percent": percent,
            "downloaded": downloaded_bytes,
            "total": None,
            "speed_bps": speed_bps,
            "eta_s": None,
            "current_file": filename,
        }

    # Check for file start line (verbose mode)
    m = _FILE_START_RE.match(s)
    if m:
        path = m.group("path").strip()
        return {
            "event": "file",
            "path": path
        }

    return None
