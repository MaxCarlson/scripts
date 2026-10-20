"""Low-overhead host RAM and NVIDIA GPU telemetry for the live dashboard."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import shutil
import subprocess
import threading

import psutil

MIB = 1024**2


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    ram_used_bytes: int | None = None
    ram_total_bytes: int | None = None
    ram_pct: float | None = None
    gpu_name: str | None = None
    gpu_utilization_pct: float | None = None
    gpu_memory_utilization_pct: float | None = None
    gpu_memory_used_bytes: int | None = None
    gpu_memory_total_bytes: int | None = None


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
    command = shutil.which("nvidia-smi")
    if not command:
        return ResourceSnapshot()
    try:
        result = subprocess.run(
            [
                command,
                "--query-gpu=name,index,utilization.gpu,utilization.memory,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ResourceSnapshot()
    if result.returncode != 0:
        return ResourceSnapshot()
    for line in result.stdout.splitlines():
        snapshot = parse_nvidia_smi_row(line)
        if snapshot.gpu_name:
            return snapshot
    return ResourceSnapshot()


def collect_resource_snapshot() -> ResourceSnapshot:
    """Read machine RAM and the first available NVIDIA GPU."""
    try:
        memory = psutil.virtual_memory()
        ram = (int(memory.used), int(memory.total), float(memory.percent))
    except (OSError, RuntimeError):
        ram = (None, None, None)
    gpu = _read_gpu()
    return ResourceSnapshot(
        ram_used_bytes=ram[0],
        ram_total_bytes=ram[1],
        ram_pct=ram[2],
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
    return f"{used_gib:.1f}/{total_gib:.1f} GiB ({used_pct:.0f}%)"


def _format_percent(value: float | None) -> str:
    return f"{value:.0f}%" if value is not None else "--"


def format_resource_line(snapshot: ResourceSnapshot) -> str:
    """Render one compact line, distinguishing GPU activity from VRAM occupancy."""
    return (
        "RESOURCES | RAM "
        f"{_format_gibibytes(snapshot.ram_used_bytes, snapshot.ram_total_bytes, snapshot.ram_pct)}"
        f" | GPU {_format_percent(snapshot.gpu_utilization_pct)}"
        f" | GPU MEM {_format_percent(snapshot.gpu_memory_utilization_pct)}"
        f" | VRAM {_format_gibibytes(snapshot.gpu_memory_used_bytes, snapshot.gpu_memory_total_bytes)}"
    )


class ResourceSampler:
    """Keep the latest hardware snapshot fresh on a daemon thread."""

    def __init__(self, interval: float = 1.0) -> None:
        self.interval = max(0.2, interval)
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
            self._stop.wait(self.interval)
