#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
procparsers: Parsers for stdout/stderr streams of external tools.

Currently supported:
- yt-dlp
- aebndl

Public API:
- parse_ytdlp_line(s: str) -> Optional[dict]
- parse_aebndl_line(s: str) -> Optional[dict]
- sanitize_line(s: str) -> str
- iter_parsed_events(tool: str, stream: TextIO, raw_log_path: Optional[Path], heartbeat_secs: float) -> Iterator[dict]
- events_to_ndjson(events: Iterable[dict]) -> Iterable[str]
"""
from .yt_dlp import parse_line as parse_ytdlp_line
from .aebndl import parse_line as parse_aebndl_line
from .utils import sanitize_line
from .stream import iter_parsed_events, events_to_ndjson

__all__ = [
    "parse_ytdlp_line",
    "parse_aebndl_line",
    "sanitize_line",
    "iter_parsed_events",
    "events_to_ndjson",
]
