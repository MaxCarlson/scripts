#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
procparsers: Parsers for stdout/stderr streams of external tools.

Currently supported:
- yt-dlp
- aebn-dl
"""
from .yt_dlp import parse_line as parse_ytdlp_line  # re-export
from .aebndl import parse_line as parse_aebndl_line
from .utils import sanitize_line
from .stream import (
    iter_stream_ytdlp,
    iter_stream_aebndl,
)

__all__ = [
    "parse_ytdlp_line",
    "parse_aebndl_line",
    "sanitize_line",
    "iter_stream_ytdlp",
    "iter_stream_aebndl",
]
