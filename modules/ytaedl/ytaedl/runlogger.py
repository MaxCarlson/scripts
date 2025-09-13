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

    Also supports a companion "raw" log (same base name with ".raw" before
    the extension) that can capture every line emitted by subprocesses with
    the same attempt counter and url index markers as the START/FINISH lines.
    """

    def __init__(self, log_path: Optional[Path]):
        self._start = time.monotonic()
        self._counter = 0
        self._lock = threading.Lock()

        self._fp = None
        self._raw_fp = None
        self._path: Optional[Path] = None

        if log_path:
            self._path = Path(log_path)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Line-buffered text mode, UTF-8
            self._fp = self._path.open("a", encoding="utf-8", buffering=1)

            # Derive raw log path: "<stem>.raw<suffix>" (e.g., log-ytaedl3.raw.txt)
            raw_name = f"{self._path.stem}.raw{self._path.suffix or ''}"
            raw_path = self._path.with_name(raw_name)
            self._raw_fp = raw_path.open("a", encoding="utf-8", buffering=1)

        # url -> (counter, start_mono)
        self._active: Dict[str, Tuple[int, float]] = {}

    # ---------------------------- lifecycle ----------------------------

    def close(self):
        if self._fp:
            self._fp.close()
        if self._raw_fp:
            self._raw_fp.close()

    # ---------------------------- helpers ----------------------------

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

    def _raw_write_line(self, line: str):
        if self._raw_fp:
            self._raw_fp.write(line + "\n")

    # ---------------------------- public API ----------------------------

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

    # New: write a raw line (verbatim payload) using same schema + attempt/index
    def raw_write(self, attempt_id: int, url_index: int, raw_text: str):
        """
        Write one line of raw subprocess output into the companion raw log,
        prefixed with the attempt counter and runtime timestamp.

        The given raw_text is written verbatim (minus any trailing newline).
        """
        raw_text = raw_text.rstrip("\r\n")
        with self._lock:
            self._raw_write_line(f"[{attempt_id:04d}][{self._now()}] RAW    [{url_index}] {raw_text}")
