#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rsync parser for --info=progress2 output.

Example progress line:
  1,234,567  12%   12.34MB/s    0:01:23 (xfr#5, to-chk=10/123)

Example per-file line:
  2024/10/15 12:34:56 [12345] >f+++++++++ path/to/file.txt

Returns normalized event dicts:
  - {'event':'progress', 'percent':..., 'total':..., 'downloaded':..., 'speed_bps':..., 'eta_s':...}
  - {'event':'file', 'path':...}
"""
from __future__ import annotations

import re
from typing import Dict, Optional

from .utils import sanitize_line

# Progress line pattern for --info=progress2
# Format: bytes  percentage  speed  eta  (xfr#N, to-chk=remaining/total)
_PROGRESS_RE = re.compile(
    r"^\s*(?P<bytes>[\d,]+)\s+"
    r"(?P<pct>\d+)%\s+"
    r"(?P<speed>[\d.]+)(?P<speed_unit>[KMG]?B)/s\s+"
    r"(?P<eta>\d+:\d+:\d+)\s+"
    r"\(xfr#(?P<xfr>\d+),?\s*to-chk=(?P<tochk>\d+)/(?P<total>\d+)\)",
    re.I
)

# Per-file line pattern (from --itemize-changes or verbose output)
# Format: "sending incremental file list" or ">f+++++++++ path/to/file"
_FILE_RE = re.compile(
    r"^(?:>f[+cdLDST.]{9}\s+|<f[+cdLDST.]{9}\s+)?(?P<path>\S.+)$"
)

# "Number of files transferred" summary line
_SUMMARY_RE = re.compile(
    r"Number\s+of\s+(?:regular\s+)?files\s+transferred:\s*(?P<count>\d+)",
    re.I
)

# "total size is" summary line (appears at end)
_TOTAL_SIZE_RE = re.compile(
    r"total\s+size\s+is\s+(?P<size>[\d,]+)",
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


def _parse_bytes(value: str) -> int:
    """Parse byte string with commas: '1,234,567' -> 1234567"""
    return int(value.replace(",", ""))


def _parse_speed(value: float, unit: str) -> float:
    """Convert speed value to bytes per second."""
    unit_upper = unit.upper()
    mult = _SIZE_UNITS.get(unit_upper, 1)
    return value * mult


def _parse_eta(eta_str: str) -> Optional[int]:
    """Parse ETA string 'HH:MM:SS' -> seconds."""
    try:
        parts = eta_str.split(":")
        if len(parts) == 3:
            h, m, s = map(int, parts)
            return h * 3600 + m * 60 + s
        elif len(parts) == 2:
            m, s = map(int, parts)
            return m * 60 + s
    except (ValueError, AttributeError):
        pass
    return None


def parse_line(line: str) -> Optional[Dict]:
    """
    Parse a single rsync output line into a normalized dict (or None if not relevant).

    Returns one of:
      - {'event':'progress', 'percent', 'total', 'downloaded', 'speed_bps', 'eta_s', 'files_done', 'files_total'}
      - {'event':'file', 'path'}
      - {'event':'summary', 'files_transferred'}
    """
    s = sanitize_line(line)

    if not s:
        return None

    # Try progress line first
    m = _PROGRESS_RE.match(s)
    if m:
        bytes_transferred = _parse_bytes(m.group("bytes"))
        percent = float(m.group("pct"))
        speed_val = float(m.group("speed"))
        speed_unit = m.group("speed_unit")
        speed_bps = _parse_speed(speed_val, speed_unit)
        eta_str = m.group("eta")
        eta_s = _parse_eta(eta_str)

        # File tracking
        xfr = int(m.group("xfr"))
        tochk = int(m.group("tochk"))
        total_files = int(m.group("total"))
        files_done = total_files - tochk

        return {
            "event": "progress",
            "percent": percent,
            "downloaded": bytes_transferred,
            "total": None,  # rsync doesn't always provide total bytes in progress line
            "speed_bps": speed_bps,
            "eta_s": eta_s,
            "files_done": files_done,
            "files_total": total_files,
            "xfr_number": xfr,
        }

    # Check for file transfer lines
    # Common patterns: "file.txt", ">f+++++++++ file.txt", "path/to/file.txt"
    # Skip known non-file lines
    skip_patterns = [
        "sending incremental file list",
        "receiving incremental file list",
        "sent ",
        "received ",
        "total size is",
        "speedup is",
        "building file list",
        "deleting ",
        "Number of files",
    ]

    for pattern in skip_patterns:
        if pattern.lower() in s.lower():
            # Check for summary lines
            if "Number of files" in s:
                sm = _SUMMARY_RE.match(s)
                if sm:
                    return {
                        "event": "summary",
                        "files_transferred": int(sm.group("count"))
                    }
            if "total size is" in s:
                sm = _TOTAL_SIZE_RE.match(s)
                if sm:
                    return {
                        "event": "summary",
                        "total_size": _parse_bytes(sm.group("size"))
                    }
            return None

    # Try to extract filename from remaining lines
    # Be conservative - only match lines that look like file paths
    if s and len(s) > 2 and not s.startswith(("rsync:", "[", "WARNING", "ERROR")):
        # Simple heuristic: if line contains a path-like string
        if "/" in s or "\\" in s or (s and not s[0].isspace()):
            m_file = _FILE_RE.match(s)
            if m_file:
                path = m_file.group("path").strip()
                if path:
                    return {
                        "event": "file",
                        "path": path
                    }

    return None
