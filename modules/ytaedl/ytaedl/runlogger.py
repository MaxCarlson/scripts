#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional, Tuple, Dict

class RunLogger:
    """
    Writes timestamped lines with a monotonically increasing attempt counter.
    Timestamps are program run-time (not wall clock).
    """
    def __init__(self, log_path: Optional[Path]):
        self._start = time.monotonic()
        self._counter = 0
        self._lock = threading.Lock()
        self._fp = None
        if log_path:
            log_path = Path(log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._fp = log_path.open("a", encoding="utf-8", buffering=1)

        # url -> (counter, start_mono)
        self._active: Dict[str, Tuple[int, float]] = {}

    def close(self):
        if self._fp:
            self._fp.close()

    def _elapsed_str(self, seconds: float) -> str:
        ms = int((seconds - int(seconds)) * 1000)
        h, rem = divmod(int(seconds), 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

    def _now(self) -> str:
        return self._elapsed_str(time.monotonic() - self._start)

    def _write(self, line: str):
        if self._fp:
            self._fp.write(line + "\n")

    def start(self, url_index: int, url: str) -> int:
        with self._lock:
            self._counter += 1
            c = self._counter
            self._active[url] = (c, time.monotonic())
            self._write(f"[{c:04d}][{self._now()}] START  [{url_index}] {url}")
            return c

    def finish(self, url_index: int, url: str, status: str, note: str = ""):
        with self._lock:
            c, began = self._active.pop(url, (self._counter, time.monotonic()))
            elapsed = self._elapsed_str(time.monotonic() - began)
            suffix = f", {note}" if note else ""
            self._write(f"[{c:04d}][{self._now()}] FINISH [{url_index}] Elapsed {elapsed}, Status={status}{suffix}")

    def info(self, msg: str):
        with self._lock:
            self._write(f"[----][{self._now()}] {msg}")
