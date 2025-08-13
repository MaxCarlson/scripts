#!/usr/bin/env python3
"""
Lightweight parser for yt-dlp console output.

What we recognize:
- Destination lines:
    [download] Destination: <full/path/or/title.ext>
- "Already downloaded" lines:
    [download] <file> has already been downloaded
    [download] File is already downloaded
- Progress lines (most common shape):
    [download]  23.4% of 50.00MiB at 3.21MiB/s ETA 00:16
    [download] 100% of 1.23GiB in 00:45
- We ignore other noise (merging formats, thumbnails, etc.)

Returned dict keys (subset depending on event):
{
  "event": "destination" | "already" | "progress" | "complete",
  "path": "<title or path>",               # destination / already
  "percent": float,                        # e.g., 23.4
  "total_bytes": int,                      # if known
  "downloaded_bytes": int,                 # if known
  "speed_Bps": float,                      # if known
  "eta_s": int | None                      # if known, -1 for N/A
}
"""

from __future__ import annotations
import re
from typing import Dict, Optional, Tuple

__all__ = [
    "parse_line",
    "parse_progress",
    "parse_destination",
    "parse_already",
    "parse_complete",
    "hms_to_seconds",
    "human_to_bytes",
]

# ---------- helpers ----------

_UNIT = {
    "B": 1,
    "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4,
    "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3, "TIB": 1024**4,
}

def human_to_bytes(num_str: str, unit_str: str) -> int:
    """Convert '12.3' + 'MiB' to integer bytes."""
    try:
        n = float(num_str.replace(",", ""))
    except Exception:
        return 0
    u = unit_str.upper()
    return int(n * _UNIT.get(u, 1))

def hms_to_seconds(s: str) -> Optional[int]:
    """Convert 'MM:SS' or 'HH:MM:SS' to seconds."""
    if not s or s == "N/A":
        return None
    parts = s.split(":")
    try:
        parts = [int(p) for p in parts]
    except Exception:
        return None
    if len(parts) == 2:
        m, sec = parts
        return m * 60 + sec
    if len(parts) == 3:
        h, m, sec = parts
        return h * 3600 + m * 60 + sec
    return None

# ---------- regex ----------

_RE_DEST = re.compile(r'^\[download\]\s+Destination:\s+(?P<path>.+?)\s*$')
_RE_ALREADY_1 = re.compile(r'^\[download\]\s+(?P<path>.+?)\s+has already been downloaded\s*$', re.IGNORECASE)
_RE_ALREADY_2 = re.compile(r'^\[download\]\s+File is already downloaded\s*$', re.IGNORECASE)

# typical progress with speed + ETA
_RE_PROGRESS = re.compile(
    r'^\[download\]\s+'
    r'(?P<pct>\d{1,3}(?:\.\d+)?)%\s+of\s+'
    r'(?P<total_num>[\d\.,]+)\s*(?P<total_unit>[KMGT]?i?B)\s+'
    r'(?:at\s+(?P<spd_num>[\d\.,]+)\s*(?P<spd_unit>[KMGT]?i?B)/s\s+)?'
    r'(?:ETA\s+(?P<eta>(?:\d{1,2}:)?\d{2}:\d{2}|\d{1,2}:\d{2}|N/A))?\s*$'
)

# completion line (100%) – sometimes no speed/ETA, sometimes "in 00:12"
_RE_COMPLETE = re.compile(
    r'^\[download\]\s+100%.*?(?:in\s+(?P<in>(?:\d{1,2}:)?\d{2}:\d{2}))?\s*$'
)

# ---------- parsers ----------

def parse_destination(line: str) -> Optional[Dict]:
    m = _RE_DEST.match(line)
    if m:
        return {"event": "destination", "path": m.group("path")}
    return None

def parse_already(line: str) -> Optional[Dict]:
    m = _RE_ALREADY_1.match(line)
    if m:
        return {"event": "already", "path": m.group("path")}
    if _RE_ALREADY_2.match(line):
        # yt-dlp usually prints "Destination:" before this; path may be unknown here
        return {"event": "already", "path": ""}
    return None

def parse_complete(line: str) -> Optional[Dict]:
    m = _RE_COMPLETE.match(line)
    if m:
        return {"event": "complete"}
    return None

def parse_progress(line: str) -> Optional[Dict]:
    m = _RE_PROGRESS.match(line)
    if not m:
        return None
    pct = float(m.group("pct"))
    total_bytes = human_to_bytes(m.group("total_num"), m.group("total_unit"))
    spd_num, spd_unit = m.group("spd_num"), m.group("spd_unit")
    speed_Bps = human_to_bytes(spd_num, spd_unit) if spd_num and spd_unit else 0.0
    eta = hms_to_seconds(m.group("eta")) if m.group("eta") else None
    downloaded_bytes = int(total_bytes * (pct / 100.0)) if total_bytes else None
    return {
        "event": "progress",
        "percent": pct,
        "total_bytes": total_bytes or None,
        "downloaded_bytes": downloaded_bytes,
        "speed_Bps": float(speed_Bps),
        "eta_s": eta if eta is not None else None,
    }

def parse_line(line: str) -> Optional[Dict]:
    """
    Try all known parses in one go.
    """
    return (
        parse_destination(line)
        or parse_already(line)
        or parse_progress(line)
        or parse_complete(line)
    )
