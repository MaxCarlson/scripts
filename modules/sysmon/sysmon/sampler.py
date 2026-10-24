from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple

import psutil
from resource_metrics import cpu_count, cpu_percent, memory_stats, nvidia_gpus, process_tree


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
    cpu_raw_pct: float = 0.0


def _gpu_info_safe() -> Tuple[List[dict], Optional[str]]:
    """Query NVIDIA devices through the shared best-effort collector."""
    rows = nvidia_gpus()
    return rows, None if rows else "GPU info unavailable"


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
        self._stop_event = threading.Event()
        self._proc_cache: dict[int, psutil.Process] = {}

        self._last_gpu_query = -float("inf")
        self._cached_gpu_rows: List[dict] = []
        self._gpu_min_interval = 1.5

        # Initialize psutil cpu percent baseline
        cpu_percent()  # establish the first non-blocking CPU baseline

    def __enter__(self) -> HardwareSampler:
        self.start()
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.stop()

    def start(self) -> None:
        """Start the background sampling thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
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
            self._stop_event.set()
            self._proc_cache.clear()
            thread = self._thread
            self._thread = None

        if thread and thread.is_alive():
            thread.join(timeout=1.0)

    def set_target_pid(self, pid: Optional[int]) -> None:
        """Set or clear the active process PID to track."""
        with self._lock:
            if self._target_pid != pid:
                self._proc_cache.clear()
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
        cpu_pct = float(cpu_percent() or 0.0)
        vm = memory_stats() or {"used": 0, "total": 0, "percent": 0.0}

        # 2. System GPU (throttled to >=1.5s interval to minimize overhead)
        now = time.monotonic()
        if now - self._last_gpu_query >= self._gpu_min_interval:
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
            ram_used_bytes=vm["used"],
            ram_total_bytes=vm["total"],
            ram_pct=float(vm["percent"]),
            gpu_name=gpu_name,
            gpu_load_pct=gpu_load,
            gpu_mem_used_bytes=gpu_mem_used,
            gpu_mem_total_bytes=gpu_mem_total,
            gpu_temp_c=gpu_temp,
        )

        # 3. Process Tree Telemetry
        proc_snap = None
        target_pid = self._target_pid
        if target_pid is not None:
            try:
                root_proc = psutil.Process(target_pid)
                zombie_status = getattr(psutil, "STATUS_ZOMBIE", "zombie")
                if root_proc.is_running() and root_proc.status() != zombie_status:
                    procs = process_tree(target_pid)

                    current_pids = {p.pid for p in procs}
                    for cached_pid in list(self._proc_cache.keys()):
                        if cached_pid not in current_pids:
                            del self._proc_cache[cached_pid]

                    total_raw_cpu = 0.0
                    total_rss = 0
                    total_threads = 0
                    num_children = len(procs) - 1

                    for p in procs:
                        try:
                            cached_proc = self._proc_cache.get(p.pid)
                            if cached_proc is None:
                                cached_proc = p
                                self._proc_cache[p.pid] = cached_proc
                                cached_proc.cpu_percent(interval=None)
                            else:
                                total_raw_cpu += cached_proc.cpu_percent(interval=None)

                            mem_info = cached_proc.memory_info()
                            total_rss += mem_info.rss
                            total_threads += cached_proc.num_threads()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            self._proc_cache.pop(p.pid, None)
                            continue

                    logical_cores = cpu_count(logical=True) or 1
                    norm_cpu = min(100.0, max(0.0, total_raw_cpu / logical_cores))
                    mem_pct = (
                        min(100.0, max(0.0, (total_rss / vm["total"]) * 100.0))
                        if vm["total"]
                        else 0.0
                    )

                    try:
                        proc_name = root_proc.name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        proc_name = f"PID {target_pid}"

                    proc_snap = ProcessStats(
                        pid=target_pid,
                        name=proc_name,
                        cpu_pct=norm_cpu,
                        cpu_raw_pct=total_raw_cpu,
                        memory_rss_bytes=total_rss,
                        memory_pct=mem_pct,
                        gpu_load_pct=None,
                        gpu_mem_used_bytes=None,
                        num_threads=max(1, total_threads),
                        num_children=max(0, num_children),
                        is_active=True,
                    )
                else:
                    if self._process_stats and self._process_stats.pid == target_pid:
                        proc_snap = ProcessStats(
                            pid=target_pid,
                            name=self._process_stats.name,
                            cpu_pct=0.0,
                            cpu_raw_pct=0.0,
                            memory_rss_bytes=self._process_stats.memory_rss_bytes,
                            memory_pct=self._process_stats.memory_pct,
                            gpu_load_pct=None,
                            gpu_mem_used_bytes=None,
                            num_threads=0,
                            num_children=0,
                            is_active=False,
                        )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                if self._process_stats and self._process_stats.pid == target_pid:
                    proc_snap = ProcessStats(
                        pid=target_pid,
                        name=self._process_stats.name,
                        cpu_pct=0.0,
                        cpu_raw_pct=0.0,
                        memory_rss_bytes=self._process_stats.memory_rss_bytes,
                        memory_pct=self._process_stats.memory_pct,
                        gpu_load_pct=None,
                        gpu_mem_used_bytes=None,
                        num_threads=0,
                        num_children=0,
                        is_active=False,
                    )

        with self._lock:
            self._system_stats = sys_snap
            if self._target_pid == target_pid:
                self._process_stats = proc_snap

    def _run_loop(self) -> None:
        """Background thread worker loop."""
        while not self._stop_event.is_set():
            try:
                self._sample_tick()
            except Exception:
                pass
            if self._stop_event.wait(timeout=self.interval):
                break
