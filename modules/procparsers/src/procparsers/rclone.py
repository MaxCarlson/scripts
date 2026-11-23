#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rclone parser for --progress and --stats output.

Example stats line (--stats-one-line):
  Transferred:   	    1.234 GiB / 10 GiB, 12%, 12.34 MiB/s, ETA 1m23s

Example JSON stats (--stats-one-line-date --log-format json):
  {"level":"info","time":"2024-10-15T12:34:56","stats":{"bytes":1234567,"totalBytes":10000000,...}}

Returns normalized event dicts:
  - {'event':'progress', 'percent':..., 'total':..., 'downloaded':..., 'speed_bps':..., 'eta_s':...}
  - {'event':'file', 'path':..., 'action':...}
"""
from __future__ import annotations

import json
import re
from typing import Dict, Optional

from .utils import sanitize_line

# Stats line pattern (--stats-one-line output)
# Format: "Transferred:   1.234 GiB / 10 GiB, 12%, 12.34 MiB/s, ETA 1m23s"
_STATS_RE = re.compile(
    r"Transferred:\s+"
    r"(?P<transferred>[\d.]+)\s*(?P<trans_unit>[KMGT]?i?B)\s*/\s*"
    r"(?P<total>[\d.]+)\s*(?P<total_unit>[KMGT]?i?B),\s*"
    r"(?P<pct>\d+)%,\s*"
    r"(?P<speed>[\d.]+)\s*(?P<speed_unit>[KMGT]?i?B)/s,\s*"
    r"ETA\s+(?P<eta>\S+)",
    re.I
)

# Simpler progress pattern without total (for ongoing transfers)
_PROGRESS_RE = re.compile(
    r"Transferred:\s+"
    r"(?P<transferred>[\d.]+)\s*(?P<trans_unit>[KMGT]?i?B),\s*"
    r"(?P<speed>[\d.]+)\s*(?P<speed_unit>[KMGT]?i?B)/s",
    re.I
)

# File operation line pattern
# Format: "2024/10/15 12:34:56 INFO  : file.txt: Copied (new)"
_FILE_RE = re.compile(
    r"(?:INFO|NOTICE)\s*:\s*(?P<path>[^:]+):\s*(?P<action>.+)$",
    re.I
)

# Size multipliers (binary: KiB, MiB, GiB; decimal: KB, MB, GB)
_SIZE_UNITS = {
    "B": 1,
    "KB": 1000,
    "MB": 1000 ** 2,
    "GB": 1000 ** 3,
    "TB": 1000 ** 4,
    "KIB": 1024,
    "MIB": 1024 ** 2,
    "GIB": 1024 ** 3,
    "TIB": 1024 ** 4,
}


def _parse_size(value: float, unit: str) -> int:
    """Convert size value with unit to bytes."""
    unit_upper = unit.upper()
    mult = _SIZE_UNITS.get(unit_upper, 1)
    return int(value * mult)


def _parse_eta(eta_str: str) -> Optional[int]:
    """
    Parse ETA string to seconds.
    Formats: '1m23s', '1h2m', '45s', '1h2m3s', '-'
    """
    if not eta_str or eta_str == "-":
        return None

    total_seconds = 0

    # Extract hours
    h_match = re.search(r"(\d+)h", eta_str)
    if h_match:
        total_seconds += int(h_match.group(1)) * 3600

    # Extract minutes
    m_match = re.search(r"(\d+)m", eta_str)
    if m_match:
        total_seconds += int(m_match.group(1)) * 60

    # Extract seconds
    s_match = re.search(r"(\d+)s", eta_str)
    if s_match:
        total_seconds += int(s_match.group(1))

    return total_seconds if total_seconds > 0 else None


def _try_parse_json(line: str) -> Optional[Dict]:
    """
    Try to parse line as JSON (from --log-format json).
    Returns normalized event dict if successful.
    """
    try:
        data = json.loads(line)

        # Check if this is a stats JSON object
        if "stats" in data:
            stats = data["stats"]
            bytes_transferred = stats.get("bytes", 0)
            total_bytes = stats.get("totalBytes", 0)
            speed_bps = stats.get("speed", 0.0)

            # Calculate percentage
            percent = 0.0
            if total_bytes > 0:
                percent = (bytes_transferred / total_bytes) * 100.0

            # ETA in seconds (if provided)
            eta_s = stats.get("eta")

            return {
                "event": "progress",
                "percent": percent,
                "downloaded": bytes_transferred,
                "total": total_bytes,
                "speed_bps": speed_bps,
                "eta_s": eta_s,
            }

        # Check for file operation logs
        if "msg" in data and "source" in data:
            msg = data["msg"]
            source = data["source"]
            if "Copied" in msg or "Moved" in msg or "Deleted" in msg:
                return {
                    "event": "file",
                    "path": source,
                    "action": msg
                }

    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    return None


def parse_line(line: str) -> Optional[Dict]:
    """
    Parse a single rclone output line into a normalized dict (or None if not relevant).

    Returns one of:
      - {'event':'progress', 'percent', 'total', 'downloaded', 'speed_bps', 'eta_s'}
      - {'event':'file', 'path', 'action'}
    """
    s = sanitize_line(line)

    if not s:
        return None

    # Try JSON parsing first (for --log-format json)
    json_evt = _try_parse_json(s)
    if json_evt:
        return json_evt

    # Try full stats line with total
    m = _STATS_RE.match(s)
    if m:
        transferred = float(m.group("transferred"))
        trans_unit = m.group("trans_unit")
        total = float(m.group("total"))
        total_unit = m.group("total_unit")
        percent = float(m.group("pct"))
        speed = float(m.group("speed"))
        speed_unit = m.group("speed_unit")
        eta_str = m.group("eta")

        downloaded_bytes = _parse_size(transferred, trans_unit)
        total_bytes = _parse_size(total, total_unit)
        speed_bps = _parse_size(speed, speed_unit)
        eta_s = _parse_eta(eta_str)

        return {
            "event": "progress",
            "percent": percent,
            "downloaded": downloaded_bytes,
            "total": total_bytes,
            "speed_bps": speed_bps,
            "eta_s": eta_s,
        }

    # Try simpler progress line without total
    m = _PROGRESS_RE.match(s)
    if m:
        transferred = float(m.group("transferred"))
        trans_unit = m.group("trans_unit")
        speed = float(m.group("speed"))
        speed_unit = m.group("speed_unit")

        downloaded_bytes = _parse_size(transferred, trans_unit)
        speed_bps = _parse_size(speed, speed_unit)

        return {
            "event": "progress",
            "percent": None,
            "downloaded": downloaded_bytes,
            "total": None,
            "speed_bps": speed_bps,
            "eta_s": None,
        }

    # Try file operation line
    m = _FILE_RE.search(s)
    if m:
        path = m.group("path").strip()
        action = m.group("action").strip()

        return {
            "event": "file",
            "path": path,
            "action": action
        }

    return None
