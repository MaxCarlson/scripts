from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple

import psutil


class TelemetryDisplayMode(Enum):
    FULL = "full"  # Option A: 2 lines (System + Active Process)
    COMPACT = "compact"  # Option C: 1 line (inline pairings)
    HIDDEN = "hidden"  # 0 lines (reclaim maximum vertical space)


@dataclass(frozen=True)
class SystemStats:
    cpu_pct: float
    ram_used_bytes: int
    ram_total_bytes: int
    ram_pct: float
    gpu_name: Optional[str] = None
    gpu_load_pct: Optional[float] = None
    gpu_mem_used_bytes: Optional[int] = None
    gpu_mem_total_bytes: Optional[int] = None
    gpu_temp_c: Optional[float] = None


@dataclass(frozen=True)
class ProcessStats:
    pid: int
    name: str
    cpu_pct: float
    memory_rss_bytes: int
    memory_pct: float
    gpu_load_pct: Optional[float] = None
    gpu_mem_used_bytes: Optional[int] = None
    num_threads: int = 1
    num_children: int = 0
    is_active: bool = True


def _gpu_info_safe() -> Tuple[List[dict], Optional[str]]:
    """Query available GPUs via GPUtil or nvidia-smi with safe fallback."""
    try:
        import GPUtil  # type: ignore

        return [
            {
                "name": g.name,
                "id": g.id,
                "load": g.load * 100.0,
                "mem_used": g.memoryUsed,
                "mem_total": g.memoryTotal,
                "temp": g.temperature,
            }
            for g in GPUtil.getGPUs()
        ], None
    except Exception:
        pass

    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,index,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.5,
        )
        rows = []
        for line in out.strip().splitlines():
            parts = [s.strip() for s in line.split(",")]
            if len(parts) >= 6:
                name, idx, util, mu, mt, temp = parts[:6]
                rows.append(
                    {
                        "name": name,
                        "id": int(idx),
                        "load": float(util),
                        "mem_used": float(mu) * 1024 * 1024,  # MiB to bytes
                        "mem_total": float(mt) * 1024 * 1024,  # MiB to bytes
                        "temp": float(temp),
                    }
                )
        return rows, None
    except Exception:
        return [], "GPU info unavailable"


class HardwareSampler:
    """Thread-safe background hardware and process telemetry sampler."""

    def __init__(self, interval: float = 0.5):
        self.interval = max(0.05, interval)
        self._target_pid: Optional[int] = None
        self._lock = threading.Lock()
        self._system_stats: Optional[SystemStats] = None
        self._process_stats: Optional[ProcessStats] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self._last_gpu_query = 0.0
        self._cached_gpu_rows: List[dict] = []
        self._gpu_min_interval = 1.5

        # Initialize psutil cpu percent baseline
        psutil.cpu_percent(interval=None)

    def start(self) -> None:
        """Start the background sampling thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._run_loop, daemon=True, name="HardwareSamplerThread"
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop background sampling and join the thread."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            thread = self._thread
            self._thread = None

        if thread and thread.is_alive():
            thread.join(timeout=1.0)

    def set_target_pid(self, pid: Optional[int]) -> None:
        """Set or clear the active process PID to track."""
        with self._lock:
            self._target_pid = pid
            if pid is None:
                self._process_stats = None

    def get_snapshots(self) -> Tuple[Optional[SystemStats], Optional[ProcessStats]]:
        """Return the latest sampled system and process telemetry snapshots."""
        with self._lock:
            return self._system_stats, self._process_stats

    def _sample_tick(self) -> None:
        """Perform one synchronous measurement sample."""
        # 1. System CPU & Memory
        cpu_pct = float(psutil.cpu_percent(interval=None))
        vm = psutil.virtual_memory()

        # 2. System GPU (throttled to >=1.5s interval to minimize overhead)
        now = time.monotonic()
        if now - self._last_gpu_query >= self._gpu_min_interval or not self._cached_gpu_rows:
            self._cached_gpu_rows, _ = _gpu_info_safe()
            self._last_gpu_query = now

        gpu_name = None
        gpu_load = None
        gpu_mem_used = None
        gpu_mem_total = None
        gpu_temp = None
        if self._cached_gpu_rows:
            primary = self._cached_gpu_rows[0]
            gpu_name = primary.get("name")
            gpu_load = primary.get("load")
            gpu_mem_used = primary.get("mem_used")
            gpu_mem_total = primary.get("mem_total")
            gpu_temp = primary.get("temp")

        sys_snap = SystemStats(
            cpu_pct=cpu_pct,
            ram_used_bytes=vm.used,
            ram_total_bytes=vm.total,
            ram_pct=float(vm.percent),
            gpu_name=gpu_name,
            gpu_load_pct=gpu_load,
            gpu_mem_used_bytes=gpu_mem_used,
            gpu_mem_total_bytes=gpu_mem_total,
            gpu_temp_c=gpu_temp,
        )

        with self._lock:
            self._system_stats = sys_snap

    def _run_loop(self) -> None:
        """Background thread worker loop."""
        while True:
            with self._lock:
                if not self._running:
                    break
            try:
                self._sample_tick()
            except Exception:
                pass
            time.sleep(self.interval)
