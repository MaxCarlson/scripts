#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Base worker utilities.

Workers print JSON lines to stdout with at least:
{
  "status": "running|completed|failed|error",
  "current_file": "...",
  "bytes_done": <int>,
  "bytes_total": <int>|null,
  "bytes_per_s": <float>|null,
  "files_done": <int>,
  "files_total": <int>|null
}
"""
from __future__ import annotations

import json
import sys
import time


def emit(status: str | None = None, **fields) -> None:
    msg = {}
    if status is not None:
        msg["status"] = status
    msg.update(fields)
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


class RateCounter:
    def __init__(self):
        self._last_t = time.time()
        self._last_b = 0

    def update(self, total_bytes: int) -> float:
        t = time.time()
        dt = max(1e-6, t - self._last_t)
        db = max(0, total_bytes - self._last_b)
        rate = db / dt
        self._last_t = t
        self._last_b = total_bytes
        return rate
