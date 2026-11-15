"""Bounded rolling history and peak tracking for monitored processes."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Set

from .models import ProcessIdentity, ProcessSample


@dataclass(frozen=True)
class HistoryPoint:
    """Single timestamped observation for a process."""

    timestamp_epoch: float
    cpu_percent: Optional[float]
    rss_bytes: Optional[int]
    io_read_rate: Optional[float]
    io_write_rate: Optional[float]
    gpu_memory_bytes: Optional[int]


@dataclass
class MetricStats:
    """Current, peak, rolling average, and short trend for one metric."""

    current: Optional[float] = None
    peak: Optional[float] = None
    peak_at_epoch: Optional[float] = None
    rolling_avg: Optional[float] = None
    trend: str = "→"


class ProcessHistory:
    """Bounded per-process history buffer with peak tracking."""

    def __init__(self, maxlen: int = 300) -> None:
        self.points: Deque[HistoryPoint] = deque(maxlen=max(1, maxlen))
        self.peak_cpu_percent: Optional[float] = None
        self.peak_cpu_at: Optional[float] = None
        self.peak_rss_bytes: Optional[int] = None
        self.peak_rss_at: Optional[float] = None
        self.peak_io_rate: Optional[float] = None
        self.peak_io_at: Optional[float] = None
        self.peak_gpu_bytes: Optional[int] = None
        self.peak_gpu_at: Optional[float] = None

    def resize(self, maxlen: int) -> None:
        if self.points.maxlen != maxlen:
            self.points = deque(self.points, maxlen=max(1, maxlen))

    def record(self, timestamp_epoch: float, sample: ProcessSample) -> None:
        point = HistoryPoint(
            timestamp_epoch=timestamp_epoch,
            cpu_percent=sample.cpu_percent,
            rss_bytes=sample.rss_bytes,
            io_read_rate=sample.io_read_rate,
            io_write_rate=sample.io_write_rate,
            gpu_memory_bytes=sample.gpu_memory_bytes,
        )
        self.points.append(point)

        if sample.cpu_percent is not None:
            if self.peak_cpu_percent is None or sample.cpu_percent > self.peak_cpu_percent:
                self.peak_cpu_percent = sample.cpu_percent
                self.peak_cpu_at = timestamp_epoch

        if sample.rss_bytes is not None:
            if self.peak_rss_bytes is None or sample.rss_bytes > self.peak_rss_bytes:
                self.peak_rss_bytes = sample.rss_bytes
                self.peak_rss_at = timestamp_epoch

        if sample.io_total_rate is not None:
            if self.peak_io_rate is None or sample.io_total_rate > self.peak_io_rate:
                self.peak_io_rate = sample.io_total_rate
                self.peak_io_at = timestamp_epoch

        if sample.gpu_memory_bytes is not None:
            if self.peak_gpu_bytes is None or sample.gpu_memory_bytes > self.peak_gpu_bytes:
                self.peak_gpu_bytes = sample.gpu_memory_bytes
                self.peak_gpu_at = timestamp_epoch

    def series(self, metric: str) -> List[Optional[float]]:
        if metric == "cpu":
            return [p.cpu_percent for p in self.points]
        if metric == "rss":
            return [float(p.rss_bytes) if p.rss_bytes is not None else None for p in self.points]
        if metric == "io_read":
            return [p.io_read_rate for p in self.points]
        if metric == "io_write":
            return [p.io_write_rate for p in self.points]
        if metric == "io_total":
            return [
                None if (p.io_read_rate is None and p.io_write_rate is None) else (p.io_read_rate or 0.0) + (p.io_write_rate or 0.0)
                for p in self.points
            ]
        if metric == "gpu_mem":
            return [float(p.gpu_memory_bytes) if p.gpu_memory_bytes is not None else None for p in self.points]
        return []

    def summary(self, metric: str) -> MetricStats:
        vals = self.series(metric)
        numeric = [v for v in vals if v is not None]
        current = vals[-1] if vals else None
        avg = (sum(numeric) / len(numeric)) if numeric else None

        peak = None
        peak_at = None
        if metric == "cpu":
            peak, peak_at = self.peak_cpu_percent, self.peak_cpu_at
        elif metric == "rss":
            peak = float(self.peak_rss_bytes) if self.peak_rss_bytes is not None else None
            peak_at = self.peak_rss_at
        elif metric == "io_total":
            peak, peak_at = self.peak_io_rate, self.peak_io_at
        elif metric == "gpu_mem":
            peak = float(self.peak_gpu_bytes) if self.peak_gpu_bytes is not None else None
            peak_at = self.peak_gpu_at
        elif numeric:
            peak = max(numeric)

        trend = "→"
        if len(numeric) >= 4:
            recent = sum(numeric[-2:]) / 2.0
            earlier = sum(numeric[-4:-2]) / 2.0
            delta = recent - earlier
            threshold = max(0.5, abs(earlier) * 0.05)
            if delta > threshold:
                trend = "↑"
            elif delta < -threshold:
                trend = "↓"

        return MetricStats(current=current, peak=peak, peak_at_epoch=peak_at, rolling_avg=avg, trend=trend)


class ProcessHistoryStore:
    """Manages bounded histories, keeping full windows for pinned/selected processes."""

    def __init__(self, *, focus_maxlen: int = 300, background_maxlen: int = 60) -> None:
        self.focus_maxlen = max(10, focus_maxlen)
        self.background_maxlen = max(5, background_maxlen)
        self._histories: Dict[ProcessIdentity, ProcessHistory] = {}

    def record_cycle(
        self,
        timestamp_epoch: float,
        samples: List[ProcessSample],
        *,
        focus_identities: Optional[Set[ProcessIdentity]] = None,
        live_identities: Optional[Set[ProcessIdentity]] = None,
    ) -> None:
        focus = focus_identities or set()
        for sample in samples:
            target_len = self.focus_maxlen if sample.identity in focus else self.background_maxlen
            hist = self._histories.get(sample.identity)
            if hist is None:
                hist = ProcessHistory(maxlen=target_len)
                self._histories[sample.identity] = hist
            else:
                hist.resize(target_len)
            hist.record(timestamp_epoch, sample)

            sample.peak_cpu_percent = hist.peak_cpu_percent
            sample.peak_cpu_at = hist.peak_cpu_at
            sample.peak_rss_bytes = hist.peak_rss_bytes
            sample.peak_rss_at = hist.peak_rss_at
            sample.peak_io_rate = hist.peak_io_rate
            sample.peak_io_at = hist.peak_io_at

        # Evict histories for processes that are neither live nor focused/pinned
        if live_identities is not None:
            stale = [
                ident
                for ident in self._histories
                if ident not in live_identities and ident not in focus
            ]
            for ident in stale:
                del self._histories[ident]

    def get(self, identity: ProcessIdentity) -> Optional[ProcessHistory]:
        return self._histories.get(identity)
