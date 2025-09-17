#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Dict, Iterable, Iterator, Optional, Tuple, TextIO

from .utils import sanitize_line
from .yt_dlp import parse_line as parse_ytdlp_line
from .aebndl import parse_line as parse_aebndl_line


def _iter_lines(stream: TextIO) -> Iterator[str]:
    """Yield sanitized lines from a text stream."""
    for raw in stream:
        s = sanitize_line(raw)
        if s:
            yield s


def iter_stream_ytdlp(stream: TextIO) -> Iterator[Tuple[Optional[Dict], str]]:
    """
    Consume a yt-dlp stdout stream and yield (parsed_event_or_None, sanitized_line).

    parsed_event_or_None is a dict like:
      - {'event':'destination', 'path':...}
      - {'event':'already'}
      - {'event':'progress', 'percent':..., 'total':..., 'downloaded':..., 'speed_bps':..., 'eta_s':...}
      - {'event':'meta', 'id':..., 'title':...}  (only if caller enables such output upstream)
    """
    for line in _iter_lines(stream):
        parsed = None
        try:
            parsed = parse_ytdlp_line(line)
        except Exception:
            parsed = None
        yield parsed, line


def iter_stream_aebndl(stream: TextIO) -> Iterator[Tuple[Optional[Dict], str]]:
    """
    Consume an aebndl stdout stream and yield (parsed_event_or_None, sanitized_line).

    parsed_event_or_None is a dict like:
      - {'event':'destination', 'path':...}
      - {'event':'aebn_progress', 'segments_done':..., 'segments_total':..., 'rate_itps':..., 'eta_s':...}
    """
    for line in _iter_lines(stream):
        parsed = None
        try:
            parsed = parse_aebndl_line(line)
        except Exception:
            parsed = None
        yield parsed, line
