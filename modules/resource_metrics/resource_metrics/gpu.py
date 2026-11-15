"""Best-effort NVIDIA telemetry via the existing nvidia-smi command line tool."""

from __future__ import annotations

import csv
import shutil
import subprocess
import time
from typing import Any, Callable, Optional

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
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode:
        return []
    return list(csv.reader(result.stdout.splitlines(), skipinitialspace=True))


def nvidia_gpus(
    *, timeout: float = 1.5, binary_name: str = "nvidia-smi", include_power: bool = False, include_uuid: bool = False
) -> list[dict[str, Any]]:
    """Discover NVIDIA GPUs and report utilization, memory bytes, temperature, and power when available.

    Scope: Host/device level.
    """
    fields = "name,index,utilization.gpu,utilization.memory,memory.used,memory.free,memory.total,temperature.gpu"
    if include_power:
        fields += ",power.draw"
    if include_uuid:
        fields = "uuid," + fields
    rows = _query(fields, timeout, binary_name=binary_name)
    devices = []
    expected_len = 8 + (1 if include_power else 0) + (1 if include_uuid else 0)
    for row in rows:
        if len(row) != expected_len:
            continue
        idx_offset = 0
        gpu_uuid = None
        if include_uuid:
            gpu_uuid = row[0].strip() or None
            idx_offset = 1
        name, index, util, mem_util, used, free, total, temp = (item.strip() for item in row[idx_offset : idx_offset + 8])
        power = row[idx_offset + 8].strip() if include_power else "N/A"
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
            if include_uuid:
                device["uuid"] = gpu_uuid
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
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
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


def gpu_process_attribution(
    pids: set[int] | list[int] | tuple[int, ...],
    *,
    timeout: float = 1.5,
    binary_name: str = "nvidia-smi",
) -> dict[str, Any]:
    """Attribute GPU compute-process memory to a collection of PIDs (e.g. a process tree).

    Note on scope: nvidia-smi compute-apps provides per-process GPU memory,
    NOT per-process GPU utilization % (which is a device-wide metric).
    """
    pid_set = {int(p) for p in pids}
    if not pid_set:
        return {"total_memory_bytes": 0, "process_memory": {}}
    apps = gpu_process_memory(timeout=timeout, binary_name=binary_name)
    total_memory = 0
    process_memory: dict[int, int] = {}
    for item in apps:
        item_pid = item.get("pid")
        mem = item.get("memory_bytes")
        if item_pid in pid_set and mem is not None:
            mem_int = int(mem)
            total_memory += mem_int
            process_memory[item_pid] = mem_int
    return {
        "total_memory_bytes": total_memory,
        "process_memory": process_memory,
    }


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


def _sample_nvml() -> Optional[dict[str, Any]]:
    """Attempt in-process GPU discovery and process attribution via pynvml."""
    try:
        import pynvml  # type: ignore
    except ImportError:
        return None

    try:
        pynvml.nvmlInit()
    except Exception:
        return None

    try:
        count = int(pynvml.nvmlDeviceGetCount())
        devices: list[dict[str, Any]] = []
        process_memory: dict[int, dict[str, Any]] = {}
        wddm_omitted = False

        for index in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            raw_name = pynvml.nvmlDeviceGetName(handle)
            name = raw_name.decode("utf-8", errors="replace") if isinstance(raw_name, bytes) else str(raw_name)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                load = float(util.gpu)
                mem_util = float(util.memory)
            except Exception:
                load = None
                mem_util = None
            try:
                temp = float(pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU))
            except Exception:
                temp = None
            try:
                power_w = float(pynvml.nvmlDeviceGetPowerUsage(handle)) / 1000.0
            except Exception:
                power_w = None

            devices.append(
                {
                    "name": name or None,
                    "id": index,
                    "load": load,
                    "memory_utilization": mem_util,
                    "mem_used": int(mem.used),
                    "mem_free": int(mem.free),
                    "mem_total": int(mem.total),
                    "temp": temp,
                    "power_w": power_w,
                }
            )

            proc_queries = []
            for fn_name in ("nvmlDeviceGetComputeRunningProcesses", "nvmlDeviceGetGraphicsRunningProcesses"):
                fn = getattr(pynvml, fn_name, None)
                if fn is None:
                    continue
                try:
                    proc_queries.extend(fn(handle))
                except Exception:
                    continue

            not_avail = getattr(pynvml, "NVML_VALUE_NOT_AVAILABLE", 0xFFFFFFFFFFFFFFFF)
            for proc_info in proc_queries:
                pid = int(getattr(proc_info, "pid", 0) or 0)
                if pid <= 0:
                    continue
                used_mem = getattr(proc_info, "usedGpuMemory", None)
                if used_mem is None or used_mem == not_avail:
                    mem_bytes = None
                    wddm_omitted = True
                else:
                    mem_bytes = int(used_mem)
                existing = process_memory.get(pid)
                if existing is None or (mem_bytes is not None and (existing["memory_bytes"] or 0) < mem_bytes):
                    process_memory[pid] = {
                        "memory_bytes": mem_bytes,
                        "gpu_id": index,
                        "provenance": "nvml",
                    }

        limitations = (
            "Windows WDDM may omit per-process GPU memory for some processes."
            if wddm_omitted
            else None
        )
        return {
            "backend": "nvml",
            "available": bool(devices),
            "devices": devices,
            "process_memory": process_memory,
            "limitations": limitations,
        }
    except Exception:
        return None
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass


class CachedGpuMonitor:
    """Throttled, cached GPU monitor preferring NVML with nvidia-smi fallback."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 4.0,
        timeout: float = 1.5,
        binary_name: str = "nvidia-smi",
        prefer_nvml: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self.timeout = float(timeout)
        self.binary_name = binary_name
        self.prefer_nvml = prefer_nvml
        self._clock = clock
        self._cached: Optional[dict[str, Any]] = None
        self._last_sampled_at: Optional[float] = None

    def snapshot(self, *, force: bool = False) -> dict[str, Any]:
        """Return cached GPU telemetry or refresh if TTL has expired."""
        now = self._clock()
        if (
            not force
            and self._cached is not None
            and self._last_sampled_at is not None
            and (now - self._last_sampled_at) < self.ttl_seconds
        ):
            result = dict(self._cached)
            result["age_seconds"] = max(0.0, now - self._last_sampled_at)
            return result

        payload: Optional[dict[str, Any]] = None
        if self.prefer_nvml:
            payload = _sample_nvml()

        if payload is None:
            devices = nvidia_gpus(timeout=self.timeout, binary_name=self.binary_name, include_power=True)
            if devices or shutil.which(self.binary_name):
                apps = gpu_process_memory(timeout=self.timeout, binary_name=self.binary_name)
                proc_mem: dict[int, dict[str, Any]] = {}
                for item in apps:
                    pid = int(item["pid"])
                    mem_val = item.get("memory_bytes")
                    proc_mem[pid] = {
                        "memory_bytes": int(mem_val) if mem_val is not None else None,
                        "gpu_id": None,
                        "provenance": "nvidia-smi",
                    }
                payload = {
                    "backend": "nvidia-smi",
                    "available": bool(devices),
                    "devices": devices,
                    "process_memory": proc_mem,
                    "limitations": "nvidia-smi compute-apps only; graphics processes and per-process utilization may be unavailable.",
                }
            else:
                payload = {
                    "backend": "unavailable",
                    "available": False,
                    "devices": [],
                    "process_memory": {},
                    "limitations": "No supported GPU backend (NVML/nvidia-smi) available.",
                }

        sampled_at = self._clock()
        payload["measured_at"] = sampled_at
        payload["age_seconds"] = 0.0
        self._cached = payload
        self._last_sampled_at = sampled_at
        return dict(payload)
