#!/usr/bin/env python3
"""
System probes for phonemon.

Designed for Termux (Android) without root. Uses psutil where possible and
best-effort direct sysfs/proc reads for GPU (Qualcomm Adreno via KGSL).

Public structures and functions are stable; avoid renaming without approval.
"""
from __future__ import annotations

import errno
import math
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None


# ===============================
# Dataclasses for probe snapshots
# ===============================

@dataclass
class CPUStats:
    per_core_percent: List[float] = field(default_factory=list)
    avg_percent: float = 0.0
    loadavg_1: float = 0.0
    loadavg_5: float = 0.0
    loadavg_15: float = 0.0
    freq_current_mhz: Optional[float] = None  # mean across cores if available


@dataclass
class MemStats:
    total: int = 0
    available: int = 0
    used: int = 0
    free: int = 0
    percent: float = 0.0
    swap_total: int = 0
    swap_used: int = 0
    swap_free: int = 0
    swap_percent: float = 0.0


@dataclass
class NetStats:
    bytes_sent: int = 0
    bytes_recv: int = 0
    packets_sent: int = 0
    packets_recv: int = 0


@dataclass
class DiskStats:
    read_bytes: int = 0
    write_bytes: int = 0


@dataclass
class GPUStats:
    percent: Optional[float] = None
    freq_mhz: Optional[float] = None
    model: Optional[str] = None
    notes: Optional[str] = None  # e.g., "kgsl:gpu_busy_percentage"


@dataclass
class ProcRow:
    pid: int
    name: str
    cpu: float
    cpu_avg_10s: float
    cpu_avg_60s: float
    mem_rss: int


# ====================
# Internal conveniences
# ====================

def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    except OSError as e:
        if e.errno not in (errno.ENOENT, errno.EPERM, errno.EACCES):
            # Unexpected errors are ignored but not fatal.
            pass
        return None


def _env_sysfs_root() -> str:
    """
    Allow tests to inject a fake root via PHONEMON_SYSFS_ROOT.
    """
    return os.environ.get("PHONEMON_SYSFS_ROOT", "")


def _rooted(p: str) -> str:
    r = _env_sysfs_root()
    return os.path.join(r, p.lstrip("/")) if r else p


# ======================
# CPU / MEM / NET / DISK
# ======================

def probe_cpu() -> CPUStats:
    per_core: List[float] = []
    avg = 0.0
    freq_mhz: Optional[float] = None

    if psutil:
        try:
            per_core = psutil.cpu_percent(interval=None, percpu=True)
            avg = float(psutil.cpu_percent(interval=None))
        except Exception:
            per_core = []
            avg = 0.0
        try:
            freqs = psutil.cpu_freq(percpu=True)
            if freqs:
                valid = [f.current for f in freqs if f and f.current]
                if valid:
                    freq_mhz = sum(valid) / len(valid)
        except Exception:
            freq_mhz = None

    try:
        la1, la5, la15 = os.getloadavg()
    except Exception:
        la1 = la5 = la15 = 0.0

    return CPUStats(
        per_core_percent=per_core,
        avg_percent=avg,
        loadavg_1=la1,
        loadavg_5=la5,
        loadavg_15=la15,
        freq_current_mhz=freq_mhz,
    )


def probe_mem() -> MemStats:
    if psutil:
        try:
            vm = psutil.virtual_memory()
            sm = psutil.swap_memory()
            return MemStats(
                total=vm.total,
                available=vm.available,
                used=vm.used,
                free=vm.free,
                percent=vm.percent,
                swap_total=sm.total,
                swap_used=sm.used,
                swap_free=sm.free,
                swap_percent=sm.percent,
            )
        except Exception:
            pass
    return MemStats()


def probe_net() -> NetStats:
    if psutil:
        try:
            n = psutil.net_io_counters()
            return NetStats(
                bytes_sent=n.bytes_sent,
                bytes_recv=n.bytes_recv,
                packets_sent=n.packets_sent,
                packets_recv=n.packets_recv,
            )
        except Exception:
            pass
    return NetStats()


def probe_disk() -> DiskStats:
    if psutil:
        try:
            d = psutil.disk_io_counters()
            return DiskStats(read_bytes=d.read_bytes, write_bytes=d.write_bytes)
        except Exception:
            pass
    return DiskStats()


# ===========
# GPU via KGSL
# ===========

_KGSL_DIR = "/sys/class/kgsl/kgsl-3d0"

def _kgsl_paths() -> Dict[str, str]:
    base = _rooted(_KGSL_DIR)
    return {
        "gpu_busy_percentage": os.path.join(base, "gpu_busy_percentage"),
        "gpubusy": os.path.join(base, "gpubusy"),  # legacy "busy total"
        "cur_freq": os.path.join(base, "devfreq", "cur_freq"),
        "gpuclk": os.path.join(base, "gpuclk"),
        "model": os.path.join(base, "gpu_model"),
    }


def probe_gpu() -> GPUStats:
    """
    Qualcomm Adreno best-effort GPU usage probe. All fields may be None if not
    exposed by the kernel/ROM or if permissions deny reads.
    """
    p = _kgsl_paths()
    percent: Optional[float] = None
    freq_mhz: Optional[float] = None
    model: Optional[str] = None
    notes: List[str] = []

    # Preferred: gpu_busy_percentage (0..100)
    txt = _read_text(p["gpu_busy_percentage"])
    if txt is not None:
        try:
            v = float(txt)
            if math.isfinite(v):
                percent = max(0.0, min(100.0, v))
                notes.append("kgsl:gpu_busy_percentage")
        except Exception:
            pass

    # Legacy: gpubusy "busy total"
    if percent is None:
        t2 = _read_text(p["gpubusy"])
        if t2:
            parts = t2.replace(",", " ").split()
            try:
                if len(parts) >= 2:
                    busy, total = float(parts[0]), float(parts[1])
                    if total > 0.0:
                        percent = max(0.0, min(100.0, 100.0 * busy / total))
                        notes.append("kgsl:gpubusy")
            except Exception:
                pass

    # Frequency from devfreq/cur_freq or gpuclk (Hz or MHz depending on kernel)
    cur = _read_text(p["cur_freq"])
    if cur and cur.strip().isdigit():
        try:
            hz = float(cur)
            freq_mhz = hz / 1_000_000.0 if hz > 50_000 else hz
            notes.append("kgsl:devfreq/cur_freq")
        except Exception:
            pass
    if freq_mhz is None:
        clk = _read_text(p["gpuclk"])
        if clk and clk.strip().isdigit():
            try:
                hz = float(clk)
                freq_mhz = hz / 1_000_000.0 if hz > 50_000 else hz
                notes.append("kgsl:gpuclk")
            except Exception:
                pass

    # Model (optional)
    m = _read_text(p["model"])
    if m:
        model = m
        notes.append("kgsl:gpu_model")

    return GPUStats(
        percent=percent,
        freq_mhz=freq_mhz,
        model=model,
        notes=", ".join(notes) if notes else None,
    )


# ============================
# Process sampling and sorting
# ============================

class RollingAVG:
    def __init__(self, maxlen: int) -> None:
        self.buf: Deque[float] = deque(maxlen=maxlen)

    def push(self, v: float) -> None:
        self.buf.append(v)

    def avg(self) -> float:
        if not self.buf:
            return 0.0
        return sum(self.buf) / len(self.buf)


class ProcSampler:
    """
    Maintains rolling CPU averages for processes without blocking the UI.
    """
    def __init__(self) -> None:
        self._avg10: Dict[int, RollingAVG] = {}
        self._avg60: Dict[int, RollingAVG] = {}
        self._last_sample: float = time.time()

        if psutil:
            for p in psutil.process_iter(attrs=["pid"]):
                try:
                    p.cpu_percent(None)  # prime
                except Exception:
                    pass

    def sample(self) -> None:
        """
        Capture a new instantaneous sample into rolling windows.
        Throttled to ~2.5 Hz (>=0.4s between samples) to avoid overhead.
        """
        if not psutil:
            return
        now = time.time()
        if now - self._last_sample < 0.4:
            return
        self._last_sample = now

        alive: set[int] = set()
        for p in psutil.process_iter(attrs=["pid", "name", "memory_info"]):
            alive.add(p.pid)
            try:
                inst = float(p.cpu_percent(None))  # non-blocking instantaneous
            except Exception:
                continue
            r10 = self._avg10.setdefault(p.pid, RollingAVG(10))
            r60 = self._avg60.setdefault(p.pid, RollingAVG(60))
            r10.push(inst)
            r60.push(inst)

        # Evict dead pids
        for d in (self._avg10, self._avg60):
            for pid in list(d.keys()):
                if pid not in alive:
                    d.pop(pid, None)

    def topn(self, n: int, sort_mode: str = "cpu") -> List[ProcRow]:
        """
        sort_mode: "cpu" | "avg10" | "avg60" | "mem"
        """
        rows: List[ProcRow] = []
        if not psutil:
            return rows

        for p in psutil.process_iter(attrs=["pid", "name", "memory_info"]):
            try:
                name = (p.info.get("name") or str(p.pid))[:40]
                cpu_now = float(p.cpu_percent(None))
                mem_rss = int(getattr(p.info.get("memory_info"), "rss", 0) or 0)
                avg10 = self._avg10.get(p.pid).avg() if p.pid in self._avg10 else 0.0
                avg60 = self._avg60.get(p.pid).avg() if p.pid in self._avg60 else 0.0
                rows.append(
                    ProcRow(
                        pid=p.pid,
                        name=name,
                        cpu=cpu_now,
                        cpu_avg_10s=avg10,
                        cpu_avg_60s=avg60,
                        mem_rss=mem_rss,
                    )
                )
            except Exception:
                continue

        key = {
            "cpu": lambda r: r.cpu,
            "avg10": lambda r: r.cpu_avg_10s,
            "avg60": lambda r: r.cpu_avg_60s,
            "mem": lambda r: r.mem_rss,
        }.get(sort_mode, lambda r: r.cpu)

        rows.sort(key=key, reverse=True)
        return rows[: max(1, n)]
