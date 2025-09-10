#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass


def _is_tty() -> bool:
    try:
        return sys.stderr.isatty()
    except Exception:
        return False


@dataclass
class _Bar:
    title: str
    total: int | None = None
    n: int = 0
    start_ts: float = 0.0
    enabled: bool = True

    def start(self, total: int | None = None):
        self.total = total
        self.start_ts = time.time()
        self.n = 0
        self._render()

    def update(self, inc: int = 1, detail: str | None = None):
        self.n += inc
        self._render(detail)

    def set(self, value: int, detail: str | None = None):
        self.n = value
        self._render(detail)

    def finish(self, detail: str | None = None):
        self._render(detail, done=True)

    def _render(self, detail: str | None = None, done: bool = False):
        if not self.enabled:
            return
        elapsed = time.time() - self.start_ts if self.start_ts else 0.0
        if self.total:
            pct = min(100.0, 100.0 * (self.n / max(1, self.total)))
            left = f"{self.n}/{self.total} {pct:5.1f}%"
        else:
            left = f"{self.n}"
        msg = f"[{self.title}] {left}  {elapsed:5.1f}s"
        if detail:
            msg += f" | {detail}"
        end = "\n" if done else "\r"
        # Print to stderr to keep stdout clean for JSON piping
        sys.stderr.write(msg + " " * max(0, 20 - len(msg)) + end)
        sys.stderr.flush()


class Progress:
    """
    Minimal progress writer that prints in-place to stderr.
    Automatically disables itself when not a TTY or when explicit disable=True.
    If the user has a 'termdash' (your module) installed with a compatible API,
    this class can be swapped to use it later; for now we keep zero-deps.
    """

    def __init__(self, enabled: bool | None = None):
        # Default: enable only if stderr is a TTY and POE2CRAFT_NO_PROGRESS is not set
        if enabled is None:
            enabled = _is_tty() and not os.getenv("POE2CRAFT_NO_PROGRESS")
        self.enabled = bool(enabled)
        self._stack: list[_Bar] = []

    @contextmanager
    def task(self, title: str, total: int | None = None):
        bar = _Bar(title=title, total=total, enabled=self.enabled)
        self._stack.append(bar)
        try:
            bar.start(total)
            yield bar
        finally:
            bar.finish()
            self._stack.pop()
