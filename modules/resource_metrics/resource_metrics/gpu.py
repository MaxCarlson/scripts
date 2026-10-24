"""Best-effort NVIDIA telemetry via the existing nvidia-smi command line tool."""

from __future__ import annotations

import csv
import shutil
import subprocess
from typing import Any, Optional

MIB = 1024**2


def _number(value: str, *, mib: bool = False) -> Optional[float]:
    value = value.strip()
    if not value or value.upper() in {"N/A", "NA", "[N/A]"}:
        return None
    try:
        parsed = float(value)
        return parsed * MIB if mib else parsed
    except ValueError:
        return None


def _query(fields: str, timeout: float = 1.5, *, binary_name: str = "nvidia-smi") -> list[list[str]]:
    binary = shutil.which(binary_name)
    if not binary:
        return []
    try:
        result = subprocess.run(
            [binary, f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode:
        return []
    return list(csv.reader(result.stdout.splitlines(), skipinitialspace=True))


def nvidia_gpus(*, timeout: float = 1.5, binary_name: str = "nvidia-smi", include_power: bool = False) -> list[dict[str, Any]]:
    """Discover NVIDIA GPUs and report utilization, memory bytes, temperature, and power when available."""
    fields = "name,index,utilization.gpu,utilization.memory,memory.used,memory.free,memory.total,temperature.gpu"
    if include_power:
        fields += ",power.draw"
    rows = _query(fields, timeout, binary_name=binary_name)
    devices = []
    for row in rows:
        if len(row) != (9 if include_power else 8):
            continue
        name, index, util, mem_util, used, free, total, temp = (item.strip() for item in row[:8])
        power = row[8].strip() if include_power else "N/A"
        try:
            device: dict[str, Any] = {
                "name": name or None,
                "id": int(index),
                "load": _number(util),
                "memory_utilization": _number(mem_util),
                "mem_used": _number(used, mib=True),
                "mem_free": _number(free, mib=True),
                "mem_total": _number(total, mib=True),
                "temp": _number(temp),
                "power_w": _number(power),
            }
        except ValueError:
            continue
        devices.append(device)
    return devices


def gpu_process_memory(*, timeout: float = 1.5, binary_name: str = "nvidia-smi") -> list[dict[str, Any]]:
    """Return best-effort NVIDIA compute-process memory attribution; unavailable values yield an empty list."""
    binary = shutil.which(binary_name)
    if not binary:
        return []
    try:
        result = subprocess.run(
            [binary, "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode:
        return []
    rows = list(csv.reader(result.stdout.splitlines(), skipinitialspace=True))
    results = []
    for row in rows:
        if len(row) != 3:
            continue
        pid, name, memory = (item.strip() for item in row)
        try:
            results.append({"pid": int(pid), "name": name or None, "memory_bytes": _number(memory, mib=True)})
        except ValueError:
            continue
    return results


def gpu_devices(*, timeout: float = 1.5) -> list[dict[str, Any]]:
    """Discover NVIDIA GPUs via nvidia-smi, falling back to the existing optional GPUtil path."""
    devices = nvidia_gpus(timeout=timeout)
    if devices:
        return devices
    try:
        import GPUtil  # type: ignore

        return [
            {
                "name": device.name,
                "id": int(device.id),
                "load": float(device.load) * 100.0,
                "memory_utilization": None,
                "mem_used": float(device.memoryUsed) * MIB,
                "mem_total": float(device.memoryTotal) * MIB,
                "temp": float(device.temperature),
                "power_w": None,
            }
            for device in GPUtil.getGPUs()
        ]
    except Exception:
        return []
