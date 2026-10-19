"""
GPU utilization telemetry provider with pluggable detection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Protocol

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
        return [
            GpuDeviceMetrics(device_id=dev, utilization_pct=pct)
            for dev, pct in self.devices.items()
        ]

    async def get_max_utilization(self) -> float:
        if not self.devices:
            return 0.0
        return max(self.devices.values())


class NvidiaGpuMonitor:
    """Read-only NVIDIA GPU monitor querying nvidia-smi with timeout and failure isolation."""

    def __init__(
        self, binary_name: str = "nvidia-smi", timeout_seconds: float = 2.0
    ) -> None:
        self.binary_name = binary_name
        self.timeout_seconds = timeout_seconds

    async def get_metrics(self) -> List[GpuDeviceMetrics]:
        import asyncio

        try:
            cmd = [
                self.binary_name,
                "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,power.draw",
                "--format=csv,noheader,nounits",
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout_seconds
            )
            if proc.returncode != 0:
                return []

            lines = stdout.decode("utf-8", errors="replace").strip().splitlines()
            metrics: List[GpuDeviceMetrics] = []
            for line in lines:
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 5:
                    idx = parts[0]
                    dev_id = f"gpu-{idx}"
                    try:
                        util = float(parts[2])
                        mem_used = float(parts[3])
                        mem_total = float(parts[4])
                        power = float(parts[5]) if len(parts) > 5 else 0.0
                    except ValueError:
                        continue
                    metrics.append(
                        GpuDeviceMetrics(
                            device_id=dev_id,
                            utilization_pct=util,
                            memory_used_mb=mem_used,
                            memory_total_mb=mem_total,
                            power_draw_w=power,
                        )
                    )
            return metrics
        except Exception as exc:
            logger.debug(
                "Failed querying NVIDIA GPU telemetry via %s: %s", self.binary_name, exc
            )
            return []

    async def get_max_utilization(self) -> float:
        metrics = await self.get_metrics()
        if not metrics:
            return 0.0
        return max(m.utilization_pct for m in metrics)
