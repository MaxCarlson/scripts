"""Low-overhead host RAM and NVIDIA GPU telemetry for the live dashboard."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import logging
import math
import threading

from typing import Callable

from resource_metrics import memory_stats, nvidia_gpus, top_process_memory
from termdash.utils import color_text

MIB = 1024**2
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    ram_used_bytes: int | None = None
    ram_total_bytes: int | None = None
    ram_pct: float | None = None
    ram_available_bytes: int | None = None
    gpu_name: str | None = None
    gpu_utilization_pct: float | None = None
    gpu_memory_utilization_pct: float | None = None
    gpu_memory_used_bytes: int | None = None
    gpu_memory_total_bytes: int | None = None


class ResourceLimitExceeded(RuntimeError):
    """A host memory limit was exceeded; stop this experiment after worker reconciliation."""


def process_memory_snapshot(limit: int = 8) -> list[dict[str, int | str]]:
    """Attribute resident memory without collecting command lines or credentials."""
    return top_process_memory(limit)


class RuntimeMemoryGuard:
    """Observe RAM during local inference and enforce only explicitly configured limits."""

    def __init__(self, max_ram_pct: float | None = None, min_available_bytes: int | None = None):
        if max_ram_pct is not None and (not math.isfinite(max_ram_pct) or not 0 < max_ram_pct <= 100):
            raise ValueError("max_ram_pct must be greater than 0 and at most 100")
        if min_available_bytes is not None and min_available_bytes < 0:
            raise ValueError("min_available_bytes must not be negative")
        self.max_ram_pct = max_ram_pct
        self.min_available_bytes = min_available_bytes
        self._next_process_sample = 0.0

    def __call__(self) -> None:
        import time

        memory = memory_stats()
        if memory is None:
            if self.max_ram_pct is not None or self.min_available_bytes is not None:
                raise ResourceLimitExceeded("Cannot enforce the explicitly configured host RAM limit: counters unavailable")
            logger.warning("Host RAM telemetry unavailable during local inference; no automatic RAM limit is configured",
                           extra={"event_type": "RUNTIME_MEMORY_UNAVAILABLE"})
            return
        percentage_exceeded = self.max_ram_pct is not None and memory["percent"] >= self.max_ram_pct
        available_exceeded = self.min_available_bytes is not None and memory["available"] < self.min_available_bytes
        exceeded = percentage_exceeded or available_exceeded
        now = time.monotonic()
        if exceeded or now >= self._next_process_sample:
            self._next_process_sample = now + 5.0
            logger.info("Runtime RAM percent=%.1f available_bytes=%s top_processes=%s",
                        memory["percent"], memory["available"], process_memory_snapshot(),
                        extra={"event_type": "RUNTIME_MEMORY"})
        if exceeded:
            limits = []
            if self.max_ram_pct is not None:
                limits.append(f"<{self.max_ram_pct:.1f}% used")
            if self.min_available_bytes is not None:
                limits.append(f">={self.min_available_bytes / 1024**3:g} GiB available")
            message = (f"Host RAM limit exceeded: {memory['percent']:.1f}% used, "
                       f"{memory['available'] / 1024**3:.1f} GiB available "
                       f"(explicit limits: {', '.join(limits)}). Cancelling the benchmark worker; "
                       "no further model loads will be attempted.")
            logger.error(message, extra={"event_type": "RUNTIME_MEMORY_LIMIT"})
            raise ResourceLimitExceeded(message)


def _number(value: str) -> float | None:
    value = value.strip()
    if not value or value.upper() in {"N/A", "NA", "[N/A]"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_nvidia_smi_row(row: str) -> ResourceSnapshot:
    """Parse one CSV row from nvidia-smi's GPU utilization query (memory in MiB)."""
    columns = next(csv.reader([row], skipinitialspace=True), [])
    if len(columns) != 6:
        return ResourceSnapshot()
    # The query includes name,index,utilization.gpu,utilization.memory,memory.used,memory.total.
    gpu_name, _, gpu_util, memory_util, memory_used, memory_total = (part.strip() for part in columns)
    used = _number(memory_used)
    total = _number(memory_total)
    return ResourceSnapshot(
        gpu_name=gpu_name or None,
        gpu_utilization_pct=_number(gpu_util),
        gpu_memory_utilization_pct=_number(memory_util),
        gpu_memory_used_bytes=int(used * MIB) if used is not None else None,
        gpu_memory_total_bytes=int(total * MIB) if total is not None else None,
    )


def _read_gpu() -> ResourceSnapshot:
    devices = nvidia_gpus()
    for device in devices:
        if device.get("name"):
            return ResourceSnapshot(
                gpu_name=device["name"],
                gpu_utilization_pct=device.get("load"),
                gpu_memory_utilization_pct=device.get("memory_utilization"),
                gpu_memory_used_bytes=device.get("mem_used"),
                gpu_memory_total_bytes=device.get("mem_total"),
            )
    return ResourceSnapshot()


def collect_resource_snapshot() -> ResourceSnapshot:
    """Read machine RAM and the first available NVIDIA GPU."""
    try:
        memory = memory_stats()
        if memory is None:
            raise OSError("memory counters unavailable")
        ram = (memory["used"], memory["total"], memory["percent"], memory["available"])
    except (OSError, RuntimeError):
        ram = (None, None, None, None)
    gpu = _read_gpu()
    return ResourceSnapshot(
        ram_used_bytes=ram[0],
        ram_total_bytes=ram[1],
        ram_pct=ram[2],
        ram_available_bytes=ram[3],
        gpu_name=gpu.gpu_name,
        gpu_utilization_pct=gpu.gpu_utilization_pct,
        gpu_memory_utilization_pct=gpu.gpu_memory_utilization_pct,
        gpu_memory_used_bytes=gpu.gpu_memory_used_bytes,
        gpu_memory_total_bytes=gpu.gpu_memory_total_bytes,
    )


def _format_gibibytes(used: int | None, total: int | None, percent: float | None = None) -> str:
    if used is None or total is None or total <= 0:
        return "--"
    used_gib = used / 1024**3
    total_gib = total / 1024**3
    used_pct = percent if percent is not None else used / total * 100
    return f"{used_gib:.1f}/{total_gib:.1f} GiB {_format_percent(used_pct)}"


def _format_percent(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "--"
    if value < 0:
        color = None
    elif value < 50:
        color = "green"
    elif value < 70:
        color = "yellow"
    elif value < 85:
        color = "orange"
    else:
        color = "red"
    return color_text(f"{int(value)}%", color)


def format_resource_line(snapshot: ResourceSnapshot) -> str:
    """Render compact, color-banded utilization while distinguishing GPU activity from VRAM."""
    return (
        "RES | RAM "
        f"{_format_gibibytes(snapshot.ram_used_bytes, snapshot.ram_total_bytes, snapshot.ram_pct)}"
        f" | GPU {_format_percent(snapshot.gpu_utilization_pct)}"
        f" | GPU-MEM {_format_percent(snapshot.gpu_memory_utilization_pct)}"
        f" | VRAM {_format_gibibytes(snapshot.gpu_memory_used_bytes, snapshot.gpu_memory_total_bytes)}"
    )


class ResourceSampler:
    """Keep the latest hardware snapshot fresh on a daemon thread."""

    def __init__(
        self,
        interval: float = 1.0,
        on_sample: Callable[[ResourceSnapshot], None] | None = None,
    ) -> None:
        self.interval = max(0.2, interval)
        self.on_sample = on_sample
        self._snapshot = ResourceSnapshot()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="agent-bench-telemetry", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        self._thread = None

    def snapshot(self) -> ResourceSnapshot:
        with self._lock:
            return self._snapshot

    def _run(self) -> None:
        while not self._stop.is_set():
            snapshot = collect_resource_snapshot()
            with self._lock:
                self._snapshot = snapshot
            if self.on_sample is not None:
                try:
                    self.on_sample(snapshot)
                except Exception:
                    logger.exception("Could not persist resource sample", extra={"event_type": "RESOURCE_LOG_ERROR"})
            self._stop.wait(self.interval)
