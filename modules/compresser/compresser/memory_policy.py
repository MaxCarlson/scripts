"""Explicit available-memory policy; reservations are estimates, not OS limits."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path
import time
from typing import Callable

MIB = 1024**2


def parse_memory_budget(value):
    if value == "auto":
        return value
    val_str = str(value).strip().lower()
    if val_str == "auto":
        return "auto"
    if val_str.endswith("%"):
        try:
            pct = float(val_str[:-1].strip())
            if not 1 <= pct <= 100:
                raise ValueError
            return f"{int(pct) if pct.is_integer() else pct}%"
        except ValueError:
            raise argparse.ArgumentTypeError("Memory percentage must be between 1% and 100%") from None
    multiplier = 1
    if val_str.endswith("gb") or val_str.endswith("gib") or val_str.endswith("g"):
        multiplier = 1024
        val_str = val_str.rstrip("gib").rstrip("gb").rstrip("g").strip()
    elif val_str.endswith("mb") or val_str.endswith("mib") or val_str.endswith("m"):
        multiplier = 1
        val_str = val_str.rstrip("mib").rstrip("mb").rstrip("m").strip()
    try:
        result = int(float(val_str) * multiplier)
        if result < 64:
            raise ValueError
        return result
    except (ValueError, OverflowError):
        raise argparse.ArgumentTypeError("Use -B auto, percentage (e.g. 50%), or memory amount (e.g. 16G, 2048M, minimum 64M)") from None


def available_memory_bytes() -> int | None:
    """Use available, never total RAM; optional psutil or native Windows/Linux."""
    try:
        import psutil

        return int(psutil.virtual_memory().available)
    except (ImportError, OSError, AttributeError, NotImplementedError):
        pass
    from cross_platform.system_utils import SystemUtils

    system = SystemUtils()
    if system.is_windows():
        import ctypes
        from ctypes import wintypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD)] + [
                (name, ctypes.c_ulonglong)
                for name in (
                    "ullTotalPhys",
                    "ullAvailPhys",
                    "ullTotalPageFile",
                    "ullAvailPageFile",
                    "ullTotalVirtual",
                    "ullAvailVirtual",
                    "ullAvailExtendedVirtual",
                )
            ]

        info = MemoryStatus()
        info.dwLength = ctypes.sizeof(info)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(info)):
            return None
        return int(info.ullAvailPhys)
    if system.is_linux():
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
        except (OSError, ValueError):
            pass
    return None


def _available(provider) -> int:
    try:
        value = provider()
        if value is None or not math.isfinite(value) or value < 0:
            raise ValueError
        return int(value)
    except (OSError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Available-memory telemetry unavailable; specify an explicit -B64..4096") from exc


@dataclass
class MemoryPolicy:
    requested: int | str
    budget_mib: int
    available_at_start: int | None
    provider: Callable
    measured_at: str
    poll_interval: float = 0.25
    _last_poll: float = float("-inf")
    _allowance: int = 0

    def diagnostics(self) -> dict:
        return {
            "requested": self.requested,
            "resolved_mib": self.budget_mib,
            "available_bytes_at_start": self.available_at_start,
            "measured_at": self.measured_at,
            "policy": (
                "20% available capped 32768MiB"
                if self.requested == "auto"
                else (f"{self.requested} available" if isinstance(self.requested, str) and self.requested.endswith("%") else "fixed")
            ),
            "note": "Per-process estimated reservations, not an OS or cross-process guarantee",
        }

    def admission_allowance(self) -> int:
        if self.requested != "auto" and not (isinstance(self.requested, str) and self.requested.endswith("%")):
            return self.budget_mib * MIB
        now = time.monotonic()
        if now - self._last_poll >= self.poll_interval:
            available = _available(self.provider)
            if self.requested == "auto":
                share = available // 5
            else:
                pct = float(self.requested[:-1])
                share = int(available * (pct / 100))
            self._allowance = min(self.budget_mib * MIB, share) if share >= 64 * MIB else 0
            self._last_poll = now
        return self._allowance


def resolve_memory_policy(value=512, *, provider=None) -> MemoryPolicy:
    try:
        value = parse_memory_budget(value)
    except argparse.ArgumentTypeError as exc:
        raise ValueError(str(exc)) from exc
    provider = provider or available_memory_bytes
    is_dynamic = value == "auto" or (isinstance(value, str) and value.endswith("%"))
    available = _available(provider) if is_dynamic else None
    if value == "auto":
        budget = min(32768, available // (5 * MIB))
    elif isinstance(value, str) and value.endswith("%"):
        pct = float(value[:-1])
        budget = int((available * (pct / 100)) // MIB)
    else:
        budget = value
    if budget < 64:
        raise ValueError("Memory allowance is below 64MiB; free memory or specify an explicit -B (e.g. -B 2048)")
    return MemoryPolicy(value, budget, available, provider, datetime.now(timezone.utc).isoformat())


def configure_memory_arguments(args) -> None:
    if not hasattr(args, "_memory_policy"):
        args._memory_policy = resolve_memory_policy(args.memory_budget_mib)
        args.memory_budget_mib = args._memory_policy.budget_mib
