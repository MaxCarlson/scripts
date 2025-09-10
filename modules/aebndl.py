#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Dict, Optional

from .utils import sanitize_line

# Known shapes (examples from typical CLIs):
#   Destination: /path/to/file.mp4
#   123/240 segments at 11.2 it/s ETA 00:35
_DEST_RE = re.compile(r"Destination:\s*(?P<path>.+)$", re.I)
_PROG_RE = re.compile(
    r"""^(?P<done>\d+)\s*/\s*(?P<total>\d+)\s*segments
        \s+at\s+(?P<rate>\d+(?:\.\d+)?)\s*it/s
        \s+ETA\s+(?P<eta>\d{2}:\d{2}(?::\d{2})?)
        \s*$""",
    re.X | re.I,
)

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

def parse_line(line: str) -> Optional[Dict]:
    """
    Parse a single aebn-dl line into a normalized dict (or None if not relevant).

    Events:
      - {'event':'destination', 'path':...}
      - {'event':'aebn_progress', 'segments_done':int, 'segments_total':int, 'rate_itps':float, 'eta_s':int}
    """
    s = sanitize_line(line)

    m = _DEST_RE.search(s)
    if m:
        return {"event": "destination", "path": m.group("path")}

    m = _PROG_RE.match(s)
    if m:
        done = int(m.group("done"))
        total = int(m.group("total"))
        rate = float(m.group("rate"))
        eta_s = _hms_to_seconds(m.group("eta"))
        return {
            "event": "aebn_progress",
            "segments_done": done,
            "segments_total": total,
            "rate_itps": rate,
            "eta_s": int(eta_s or 0),
        }

    return None
