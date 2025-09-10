#!/usr/bin/env python3
from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional


@dataclass
class _Bar:
    title: str
    total: Optional[int] = None
    n: int = 0
    start_ts: float = 0.0
    last_len: int = 0
    enabled: bool = True

    def start(self):
        self.start_ts = time.time()
        self._render()

    def update(self, inc: int = 1, detail: str = ""):
        self.n += inc
        self._render(detail)

    def set(self, value: int, detail: str = ""):
        self.n = value
        self._render(detail)

    def finish(self, detail: str = ""):
        self._render(detail, done=True)

    def _render(self, detail: str = "", done: bool = False):
        if not self.enabled:
            return
        elapsed = time.time() - (self.start_ts or time.time())
        if self.total:
            pct = min(100.0, 100.0 * (self.n / max(1, self.total)))
            left = f"{self.n}/{self.total} {pct:5.1f}%"
        else:
            left = f"{self.n}"
        msg = f"[{self.title}] {left}  {elapsed:4.1f}s"
        if detail:
            msg += f" | {detail}"
        pad = " " * max(0, self.last_len - len(msg))
        sys.stderr.write("\r" + msg + pad)
        if done:
            sys.stderr.write("\n")
        sys.stderr.flush()
        self.last_len = len(msg)


class Progress:
    """
    Minimal progress printer (stderr). It never pollutes stdout, so tests/scripts stay stable.
    """

    def __init__(self, enabled: Optional[bool] = None):
        # enable when stderr is a TTY by default
        try:
            default_enabled = sys.stderr.isatty()
        except Exception:
            default_enabled = False
        self.enabled = default_enabled if enabled is None else enabled

    @contextmanager
    def task(self, title: str, total: Optional[int] = None):
        bar = _Bar(title=title, total=total, enabled=self.enabled)
        bar.start()
        try:
            yield bar
        finally:
            bar.finish()
