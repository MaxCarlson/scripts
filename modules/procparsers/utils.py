#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import re

_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

def sanitize_line(s: str) -> str:
    """
    Strip ANSI sequences and trailing newlines/carriage returns.
    Keep other spacing intact for regexes to match reliably.
    """
    if s is None:
        return ""
    s = _ANSI_RE.sub("", s)
    return s.rstrip("\r\n")
