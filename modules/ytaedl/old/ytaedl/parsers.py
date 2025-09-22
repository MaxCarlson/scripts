"""Parsers for yt-dlp and aebndl outputs (matches tests)."""
from __future__ import annotations

import re
from typing import Dict, Optional


def sanitize_line(s: str) -> str:
    """Keep simple to satisfy tests: strip trailing newlines."""
    return s.rstrip("\r\n")


# ----------------- yt-dlp -----------------

_YTDLP_DEST_RE = re.compile(r"^\[download\]\s+Destination:\s*(?P<path>.+)$", re.IGNORECASE)
_YTDLP_ALREADY_RE = re.compile(
    r"^\[download\]\s+.+?\s+has\s+already\s+been\s+downloaded\s*$", re.IGNORECASE
)
_YTDLP_META_RE = re.compile(r"^TDMETA\t(?P<id>[^\t]+)\t(?P<title>.*)$")
_YTDLP_PROGRESS_RE = re.compile(
    r"^\[download\]\s+"
    r"(?P<pct>\d+(?:\.\d+)?)%\s+of\s+(?P<total_num>[\d\.]+)\s*(?P<total_unit>[KMG]?i?B)"
    r"(?:\s+at\s+(?P<speed_num>[\d\.]+)\s*(?P<speed_unit>[KMG]?i?B)/s)?"
    r"(?:\s+ETA\s+(?P<eta_mm>\d{2}):(?P<eta_ss>\d{2}))?"
    r".*$",
    re.IGNORECASE,
)


def _to_bytes(num_str: str, unit: str) -> int:
    """Convert KiB/MiB/GiB (or KB/MB/GB) to bytes."""
    num = float(num_str)
    unit = (unit or "").upper()
    if unit in ("KB", "KIB"):
        return int(num * 1024)
    if unit in ("MB", "MIB"):
        return int(num * 1024 * 1024)
    if unit in ("GB", "GIB"):
        return int(num * 1024 * 1024 * 1024)
    return int(num)


def parse_ytdlp_line(line: str) -> Optional[Dict]:
    """
    Parse a single yt-dlp output line.

    Returns a dict with:
      - {"event": "meta", "id": ..., "title": ...}
      - {"event": "destination", "path": ...}
      - {"event": "already"}
      - {"event": "progress", "percent": float, "downloaded": int, "total": int,
         "speed_bps": Optional[int], "eta_s": Optional[int]}
    or None if not matched.
    """
    m = _YTDLP_META_RE.match(line)
    if m:
        return {"event": "meta", "id": m.group("id"), "title": m.group("title")}

    m = _YTDLP_DEST_RE.match(line)
    if m:
        return {"event": "destination", "path": m.group("path")}

    if _YTDLP_ALREADY_RE.match(line):
        return {"event": "already"}

    m = _YTDLP_PROGRESS_RE.match(line)
    if m:
        total = _to_bytes(m.group("total_num"), m.group("total_unit"))
        pct_float = float(m.group("pct"))
        downloaded = int(total * (pct_float / 100.0))

        speed_bps = None
        if m.group("speed_num") and m.group("speed_unit"):
            speed_bps = _to_bytes(m.group("speed_num"), m.group("speed_unit"))

        eta_s = None
        if m.group("eta_mm") and m.group("eta_ss"):
            eta_s = int(m.group("eta_mm")) * 60 + int(m.group("eta_ss"))

        return {
            "event": "progress",
            "percent": pct_float,
            "downloaded": downloaded,
            "total": total,
            "speed_bps": speed_bps,
            "eta_s": eta_s,
        }

    return None


# ----------------- aebndl -----------------
_AEBN_DEST_RE = re.compile(r"^Output file name:\s*(?P<path>.+)$", re.IGNORECASE)
_AEBN_PROGRESS_RE = re.compile(
    r"^(?P<stream>Audio|Video)\s+download:\s*"
    r"(?P<pct>\d+)%\s*\|\s*(?P<done>\d+)/(?P<total>\d+)\s*"
    r"\[\d{2}:\d{2}<(?P<eta_mm>\d{2}):(?P<eta_ss>\d{2}),\s*(?P<ips>[\d\.]+)it/s\]\s*$",
    re.IGNORECASE,
)


def parse_aebndl_line(line: str) -> Optional[Dict[str, object]]:
    m = _AEBN_DEST_RE.match(line)
    if m:
        return {"event": "destination", "path": m.group("path")}

    m = _AEBN_PROGRESS_RE.match(line)
    if m:
        eta_s = int(m.group("eta_mm")) * 60 + int(m.group("eta_ss"))
        return {
            "event": "aebn_progress",
            "stream": m.group("stream").lower(),
            "segments_done": int(m.group("done")),
            "segments_total": int(m.group("total")),
            "rate_itps": float(m.group("ips")),
            "eta_s": eta_s,
        }

    return None
