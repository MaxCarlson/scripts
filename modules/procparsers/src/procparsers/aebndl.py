#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from typing import Dict, Optional


_DEST_RE = re.compile(r"^Destination:\s*(?P<path>.+)$")
_PROG_RE = re.compile(
    r"^(?P<done>\d+)\/(?P<total>\d+)\s+segments\s+at\s+(?P<rate>[0-9.]+)\s+it\/s\s+ETA\s+(?P<eta>(?:\d{2}:\d{2}(?::\d{2})?))$",
    re.I,
)


def _hms_to_seconds(hms: str) -> Optional[int]:
    parts = [int(x) for x in hms.split(":")]
    if len(parts) == 2:
        # AEBN progress uses HH:MM when two fields are present (00:35 -> 35 minutes)
        h, m = parts
        return h * 3600 + m * 60
    if len(parts) == 3:
        h, m, s = parts
        return h * 3600 + m * 60 + s
    return None


def parse_line(line: str) -> Optional[Dict]:
    """
    Parse a single aebndl line.
    - If it's JSON, return the JSON dict as-is.
    - Else, support simple text forms used by earlier tooling/tests.
    """
    if not line:
        return None
    s = line.strip()

    # Try JSON first
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    m = _DEST_RE.match(s)
    if m:
        return {"event": "destination", "path": m.group("path")}

    m = _PROG_RE.match(s)
    if m:
        done = int(m.group("done"))
        total = int(m.group("total"))
        rate = float(m.group("rate"))
        eta = _hms_to_seconds(m.group("eta"))
        return {
            "event": "aebn_progress",
            "segments_done": done,
            "segments_total": total,
            "rate_itps": rate,
            "eta_s": eta,
        }

    return None
