#!/usr/bin/env python3
"""
Lightweight parser for yt-dlp console output.

Recognized events (returned as dicts; keys present depend on event):

- "meta" (our injected print):
    TDMETA\t<ID>\t<TITLE>
    keys: id, title

- "destination":
    [download] Destination: <full/path/or/title.ext>
    keys: path

- "already":
    [download] <file> has already been downloaded
    [download] File is already downloaded
    [download] ...already...downloaded...
    keys: path (may be "" if not given)

- "resume":
    [download] Resuming download at byte 16777216
    keys: from_byte (int)

- "progress":
    [download]  23.4% of 50.00MiB at 3.21MiB/s ETA 00:16
    [download]  23.4% of ~50.00MiB at 3.21MiB/s ETA 00:16
    keys: percent, total_bytes, downloaded_bytes, speed_Bps, eta_s

- "complete":
    [download] 100% of 1.23GiB in 00:45
    [download] 100%
    keys: none

- "extract" (one per URL before work starts on it):
    [SomethingSite] Extracting URL: https://example/...
    keys: url

- "error":
    ERROR: <message>
    keys: message
"""

from __future__ import annotations
import re
from typing import Dict, Optional

__all__ = [
    "parse_line",
    "parse_meta",
    "parse_destination",
    "parse_already",
    "parse_resume",
    "parse_progress",
    "parse_complete",
    "parse_extract",
    "parse_error",
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
    try:
        n = float((num_str or "").replace(",", ""))
    except Exception:
        return 0
    u = (unit_str or "").upper()
    return int(n * _UNIT.get(u, 1))

def hms_to_seconds(s: str) -> Optional[int]:
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
_RE_META = re.compile(r'^TDMETA\t(?P<id>[^\t]+)\t(?P<title>.*)\s*$')
_RE_DEST = re.compile(r'^\\[download]\\s+Destination:\\s+(?P<path>.+?)\\s*$')
_RE_ALREADY_1 = re.compile(r'^\\[download]\\s+(?P<path>.+?)\\s+has already been downloaded\\s*$', re.IGNORECASE)
_RE_ALREADY_2 = re.compile(r'^\\[download]\\s+File is already downloaded\\s*$')
_RE_ALREADY_3 = re.compile(r'^\\[download].*already.*downloaded.*$')
_RE_RESUME = re.compile(r'^\\[download]\\s+Resuming download at byte\\s+(?P<byte>\\d+)\\s*$')
_RE_PROGRESS = re.compile(
    r'^\\[download]\\s+'
    r'(?P<pct>\\d{1,3}(?:\\.\\d+)?)%\\s+of\\s+~?(?P<total_num>[\\d\\.,]+)\\s*(?P<total_unit>[KMGT]?i?B)\\s+'
    r'(?:at\\s+(?P<spd_num>[\\d\\.,]+)\\s*(?P<spd_unit>[KMGT]?i?B)/s\\s+)?'
    r'(?:ETA\\s+(?P<eta>(?:\\d{1,2}:)?\\d{2}:\\d{2}|N/A))?\\s*$'
)
_RE_COMPLETE = re.compile(r'^\\[download]\\s+100%.*?(?:\\s+in\\s+(?P<in>(?:\\d{1,2}:)?\\d{2}:\\d{2}))?\\s*$')
_RE_EXTRACT = re.compile(r'^\\[[^\\]]+\]\\s+Extracting URL:\\s+(?P<url>\\S+)\\s*$')
_RE_ERROR = re.compile(r'^\\s*ERROR:\\s*(?P<msg>.+?)\\s*$')

# ---------- parsers ----------
def parse_meta(line: str) -> Optional[Dict]:
    m = _RE_META.match(line)
    if m:
        return {"event": "meta", "id": m.group("id"), "title": m.group("title")}
    return None

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
        return {"event": "already", "path": ""}
    if _RE_ALREADY_3.match(line):
        return {"event": "already", "path": ""}
    return None

def parse_resume(line: str) -> Optional[Dict]:
    m = _RE_RESUME.match(line)
    if m:
        try:
            val = int(m.group("byte"))
        except Exception:
            val = 0
        return {"event": "resume", "from_byte": val}
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

def parse_complete(line: str) -> Optional[Dict]:
    m = _RE_COMPLETE.match(line)
    if m:
        return {"event": "complete"}
    return None

def parse_extract(line: str) -> Optional[Dict]:
    m = _RE_EXTRACT.match(line)
    if m:
        return {"event": "extract", "url": m.group("url")}
    return None

def parse_error(line: str) -> Optional[Dict]:
    m = _RE_ERROR.match(line)
    if m:
        return {"event": "error", "message": m.group("msg")}
    return None

def parse_line(line: str) -> Optional[Dict]:
    # Order matters: meta → destination → already → resume → progress → complete → extract → error
    return (
        parse_meta(line)
        or parse_destination(line)
        or parse_already(line)
        or parse_resume(line)
        or parse_progress(line)
        or parse_complete(line)
        or parse_extract(line)
        or parse_error(line)
    )
