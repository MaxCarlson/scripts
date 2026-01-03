#!/usr/bin/env python3
"""
RotatingText: cycles through paragraphs into a TermDash/SimpleBoard stat.

Features:
- Variable dwell time based on paragraph length (words_per_second, min/max bounds)
- Time-based rotation plus manual advance()
- Stops cleanly and is safe if paragraphs are empty
"""

from __future__ import annotations

import time
from threading import Event, Thread
from typing import Iterable, List, Optional


class RotatingText:
    def __init__(
        self,
        board,
        line_name: str,
        stat_name: str,
        paragraphs: Iterable[str],
        *,
        min_interval_s: float = 3.0,
        max_interval_s: float = 25.0,
        words_per_second: float = 2.0,
    ) -> None:
        self.board = board
        self.line = line_name
        self.stat = stat_name
        self.paragraphs: List[str] = [p.strip() for p in paragraphs if str(p or "").strip()]
        self.min_interval_s = max(0.5, float(min_interval_s))
        self.max_interval_s = max(self.min_interval_s, float(max_interval_s))
        self.words_per_second = max(0.1, float(words_per_second))

        self._stop = Event()
        self._advance = Event()
        self._thread: Optional[Thread] = None

    def _interval_for(self, text: str) -> float:
        words = max(1, len(text.split()))
        est = words / self.words_per_second
        return max(self.min_interval_s, min(self.max_interval_s, est))

    def start(self) -> None:
        if not self.paragraphs:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._advance.clear()
        self._thread = Thread(target=self._run, name="RotatingText", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        self._stop.set()
        self._advance.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def advance(self) -> None:
        self._advance.set()

    def _sleep_or_advance(self, seconds: float) -> bool:
        """Sleep for `seconds` unless advance/stop is triggered.

        Returns True if we should keep looping (normal sleep) and False if we
        should immediately advance to the next paragraph.
        """

        deadline = time.time() + max(0.0, seconds)
        while not self._stop.is_set() and time.time() < deadline:
            remaining = max(0.0, deadline - time.time())
            wait_for = min(0.2, remaining)
            if self._advance.wait(timeout=wait_for):
                self._advance.clear()
                return False
        return True

    def _run(self) -> None:
        for text in self.paragraphs:
            if self._stop.is_set():
                break
            try:
                self.board.update(self.line, self.stat, text)
            except Exception:
                pass
            dwell = self._interval_for(text)
            should_continue = self._sleep_or_advance(dwell)
            if self._stop.is_set():
                break
            if not should_continue:
                continue
        # no loop after last paragraph; stop naturally


__all__ = ["RotatingText"]
