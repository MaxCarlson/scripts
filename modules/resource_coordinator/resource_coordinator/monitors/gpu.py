"""
GPU utilization telemetry provider with pluggable detection.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Protocol

from resource_metrics import nvidia_gpus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GpuDeviceMetrics:
    device_id: str
    utilization_pct: float
    memory_used_mb: float = 0.0
    memory_total_mb: float = 0.0
    power_draw_w: float = 0.0


class GpuMonitor(Protocol):
    """Protocol for GPU metric providers."""

    async def get_metrics(self) -> List[GpuDeviceMetrics]: ...
    async def get_max_utilization(self) -> float: ...


class MockGpuMonitor:
    """Mock GPU monitor for testing and systems without GPU telemetry."""

    def __init__(self, default_utilization: float = 0.0) -> None:
        self.default_utilization = default_utilization
        self.devices: Dict[str, float] = {"gpu-0": default_utilization}

    def set_utilization(self, device_id: str, pct: float) -> None:
        self.devices[device_id] = max(0.0, min(100.0, pct))

    async def get_metrics(self) -> List[GpuDeviceMetrics]:
        return [GpuDeviceMetrics(device_id=dev, utilization_pct=pct) for dev, pct in self.devices.items()]

    async def get_max_utilization(self) -> float:
        if not self.devices:
            return 0.0
        return max(self.devices.values())


class NvidiaGpuMonitor:
    """Read-only NVIDIA GPU monitor querying nvidia-smi with timeout and failure isolation."""

    def __init__(self, binary_name: str = "nvidia-smi", timeout_seconds: float = 2.0) -> None:
        self.binary_name = binary_name
        self.timeout_seconds = timeout_seconds

    async def get_metrics(self) -> List[GpuDeviceMetrics]:
        import asyncio

        try:
            devices = await asyncio.to_thread(
                nvidia_gpus, timeout=self.timeout_seconds, binary_name=self.binary_name, include_power=True
            )
            metrics = []
            for device in devices:
                util = device.get("load")
                memory_used = device.get("mem_used")
                memory_total = device.get("mem_total")
                power = device.get("power_w")
                if None in (util, memory_used, memory_total, power):
                    continue
                values = (float(util), float(memory_used), float(memory_total), float(power))
                if not all(math.isfinite(value) for value in values):
                    continue
                util, memory_used, memory_total, power = values
                if not 0 <= util <= 100 or not 0 <= memory_used <= memory_total or memory_total <= 0 or power < 0:
                    continue
                metrics.append(
                    GpuDeviceMetrics(
                        device_id=f"gpu-{device['id']}",
                        utilization_pct=util,
                        memory_used_mb=memory_used / (1024**2),
                        memory_total_mb=memory_total / (1024**2),
                        power_draw_w=power,
                    )
                )
            return metrics
        except Exception as exc:
            logger.debug("Failed querying NVIDIA GPU telemetry via %s: %s", self.binary_name, exc)
            return []

    async def get_max_utilization(self) -> float:
        metrics = await self.get_metrics()
        if not metrics:
            raise RuntimeError("GPU telemetry is unavailable; utilization and execution state are unknown")
        return max(m.utilization_pct for m in metrics)
