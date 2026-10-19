"""
CPU utilization telemetry provider.
"""

from __future__ import annotations

import time
from typing import List

import psutil


class CpuMonitor:
    """Monitors CPU utilization with rolling sample history."""

    def __init__(self, sample_history_seconds: float = 300.0) -> None:
        self.sample_history_seconds = sample_history_seconds
        self._samples: List[tuple[float, float]] = []

    def sample(self) -> float:
        """Take a sample of total CPU utilization percent."""
        pct = float(psutil.cpu_percent(interval=None))
        now = time.time()
        self._samples.append((now, pct))
        self._prune(now)
        return pct

    def get_latest(self) -> float:
        """Return the most recent CPU sample, or take one if none recorded."""
        if not self._samples:
            return self.sample()
        return self._samples[-1][1]

    def get_average(self, window_seconds: float = 60.0) -> float:
        """Return the average CPU percent over the given window."""
        now = time.time()
        self._prune(now)
        cutoff = now - max(1.0, window_seconds)
        matching = [pct for t, pct in self._samples if t >= cutoff]
        if not matching:
            return self.get_latest()
        return sum(matching) / len(matching)

    def _prune(self, now: float) -> None:
        cutoff = now - self.sample_history_seconds
        self._samples = [(t, pct) for t, pct in self._samples if t >= cutoff]
