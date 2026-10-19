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
