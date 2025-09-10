#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Dict, Optional

from .utils import sanitize_line

# ---- Patterns --------------------------------------------------------------

# Custom meta line we print via: --print "TDMETA\t%(id)s\t%(title)s"
_META_RE = re.compile(r"^TDMETA\t(?P<id>[^\t]+)\t(?P<title>.+)$")

# Destination emitted by yt-dlp
_DEST_RE = re.compile(r"^\[download\]\s+Destination:\s*(?P<path>.+)$")

# "Already" variants:
#   [download] File is already downloaded and merged
#   [download] <file.ext> has already been downloaded
#   [download] <file.ext> has already been downloaded and merged
_ALREADY_RES = [
    re.compile(r"^\[download\]\s+File\s+is\s+already\s+downloaded\s+and\s+merged\s*$", re.I),
    re.compile(r"^\[download\]\s+.+?\s+has\s+already\s+been\s+downloaded(?:\s+and\s+merged)?\s*$", re.I),
]

# Progress lines usually look like:
#   [download]  10.1% of 48.97MiB at 2.11MiB/s ETA 00:37
#   [download] 100% of 25.00MiB in 00:30
_PROGRESS_RE = re.compile(
    r"""^\[download\]\s+
        (?P<pct>\d{1,3}(?:\.\d+)?)%\s+of\s+
        (?P<total_val>\d+(?:\.\d+)?)\s*(?P<total_unit>[KMGT]?i?B)\s*
        (?:
            \s+at\s+(?P<speed_val>\d+(?:\.\d+)?)\s*(?P<speed_unit>[KMGT]?i?B)/s\s*
        )?
        (?:
            \s+ETA\s+(?P<eta>\d{2}:\d{2}(?::\d{2})?) |
            \s+in\s+(?P<intime>\d{2}:\d{2}(?::\d{2})?)
        )
        \s*$
    """,
    re.X,
)

# ---- Helpers ---------------------------------------------------------------

_SIZE_MULTS_1024 = {"KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4}
_SIZE_MULTS_1000 = {"KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4}

def _unit_to_bytes(value: float, unit: str) -> Optional[int]:
    unit = unit or ""
    unit = unit.strip()
    if unit == "B":
        return int(value)
    if unit in _SIZE_MULTS_1024:
        return int(value * _SIZE_MULTS_1024[unit])
    if unit in _SIZE_MULTS_1000:
        return int(value * _SIZE_MULTS_1000[unit])
    # Some builds show lowercase like "mib/s"
    u = unit.upper()
    if u in _SIZE_MULTS_1024:
        return int(value * _SIZE_MULTS_1024[u])
    if u in _SIZE_MULTS_1000:
        return int(value * _SIZE_MULTS_1000[u])
    return None

def _hms_to_seconds(hms: str) -> Optional[int]:
    if not hms:
        return None
    parts = [int(x) for x in hms.split(":")]
    if len(parts) == 2:
        m, s = parts
        return m * 60 + s
    if len(parts) == 3:
        h, m, s = parts
        return h * 3600 + m * 60 + s
    return None

# ---- Public API ------------------------------------------------------------

def parse_line(line: str) -> Optional[Dict]:
    """
    Parse a single yt-dlp line into a normalized dict (or None if not relevant).

    Returns a dict with at least an 'event' key in:
      - {'event':'meta', 'id':..., 'title':...}
      - {'event':'destination', 'path':...}
      - {'event':'already'}
      - {
          'event':'progress',
          'percent': float,
          'total': int (bytes),
          'downloaded': int (bytes),
          'speed_bps': float or None,
          'eta_s': int or None
        }

    Unrecognized lines -> None (let caller log as raw).
    """
    s = sanitize_line(line)

    # 1) metadata
    m = _META_RE.match(s)
    if m:
        return {"event": "meta", "id": m.group("id"), "title": m.group("title")}

    # 2) destination
    m = _DEST_RE.match(s)
    if m:
        return {"event": "destination", "path": m.group("path")}

    # 3) already
    for rx in _ALREADY_RES:
        if rx.match(s):
            return {"event": "already"}

    # 4) progress
    m = _PROGRESS_RE.match(s)
    if m:
        pct = float(m.group("pct"))
        total_val = float(m.group("total_val"))
        total_unit = m.group("total_unit")
        total_bytes = _unit_to_bytes(total_val, total_unit) or 0
        downloaded = int(round((pct / 100.0) * total_bytes))

        speed_bps = None
        if m.group("speed_val") and m.group("speed_unit"):
            sp_val = float(m.group("speed_val"))
            sp_unit = m.group("speed_unit")
            speed_bps = float(_unit_to_bytes(sp_val, sp_unit) or 0)

        eta_s = None
        if m.group("eta"):
            eta_s = _hms_to_seconds(m.group("eta"))
        elif m.group("intime"):
            # final completion line: treat as eta 0
            eta_s = 0

        return {
            "event": "progress",
            "percent": pct,
            "total": total_bytes,
            "downloaded": downloaded,
            "speed_bps": speed_bps,
            "eta_s": eta_s,
        }

    # 5) nothing matched
    return None
