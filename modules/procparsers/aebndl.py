#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Dict, Optional

from .utils import sanitize_line

# Examples seen in the wild (aebn-vod-downloader):
#   Destination: D:\path\file.mp4
#   123/240 segments at 11.2 it/s ETA 00:35
#   123/240 segments (51.2%) ETA 00:35
#   Downloading segments: 123/240 (51.2%) at 11.2 it/s ETA 00:35
#   Joining segments...
#   Muxing...
#
# We normalize to:
#   {'event':'destination', 'path':...}
#   {'event':'progress', 'segments_done':int, 'segments_total':int,
#    'percent':float|None, 'rate_itps':float|None, 'eta_s':int|None}
#   {'event':'stage', 'name':'joining'|'muxing'}

_DEST_RE = re.compile(r"Destination:\s*(?P<path>.+)$", re.I)

# Allow several progress shapes
_PROG_SHAPES = [
    re.compile(
        r"""^(?P<done>\d+)\s*/\s*(?P<total>\d+)\s*segments
            \s+at\s+(?P<rate>\d+(?:\.\d+)?)\s*it/s
            \s+ETA\s+(?P<eta>\d{2}:\d{2}(?::\d{2})?)\s*$
        """,
        re.X | re.I,
    ),
    re.compile(
        r"""^(?P<done>\d+)\s*/\s*(?P<total>\d+)\s*segments
            \s*(?P<pct>\d+(?:\.\d+)?)%
            \s+ETA\s+(?P<eta>\d{2}:\d{2}(?::\d{2})?)\s*$
        """,
        re.X | re.I,
    ),
    re.compile(
        r"""^Downloading\s+segments:\s*
            (?P<done>\d+)\s*/\s*(?P<total>\d+)
            \s*(?P<pct>\d+(?:\.\d+)?)%
            (?:\s+at\s+(?P<rate>\d+(?:\.\d+)?)\s*it/s)?
            \s+ETA\s+(?P<eta>\d{2}:\d{2}(?::\d{2})?)\s*$
        """,
        re.X | re.I,
    ),
]

_STAGE_RE = [
    (re.compile(r"\bjoining\s+segments\b", re.I), "joining"),
    (re.compile(r"\bmuxing\b", re.I), "muxing"),
]

def _hms_to_seconds(hms: str) -> Optional[int]:
    if not hms:
        return None
    parts = [int(x) for x in hms.split(":")]
    if len(parts) == 2:
        h, m = parts
        return h * 3600 + m * 60
    if len(parts) == 3:
        h, m, s = parts
        return h * 3600 + m * 60 + s
    return None

def parse_line(line: str) -> Optional[Dict]:
    """
    Parse a single aebndl line into a normalized dict (or None if not relevant).

    Events:
      - {'event':'destination', 'path':...}
      - {'event':'progress', 'segments_done':int, 'segments_total':int,
         'percent':float|None, 'rate_itps':float|None, 'eta_s':int|None}
      - {'event':'stage', 'name':'joining'|'muxing'}
    """
    s = sanitize_line(line)

    m = _DEST_RE.search(s)
    if m:
        return {"event": "destination", "path": m.group("path")}

    for rx in _PROG_SHAPES:
        m = rx.match(s)
        if m:
            done = int(m.group("done"))
            total = int(m.group("total"))
            pct = float(m.group("pct")) if m.groupdict().get("pct") else (done * 100.0 / total if total else None)
            rate = float(m.group("rate")) if m.groupdict().get("rate") else None
            eta_s = _hms_to_seconds(m.group("eta")) if m.groupdict().get("eta") else None
            return {
                "event": "progress",
                "segments_done": done,
                "segments_total": total,
                "percent": pct,
                "rate_itps": rate,
                "eta_s": int(eta_s or 0) if eta_s is not None else None,
            }

    for rx, name in _STAGE_RE:
        if rx.search(s):
            return {"event": "stage", "name": name}

    return None
