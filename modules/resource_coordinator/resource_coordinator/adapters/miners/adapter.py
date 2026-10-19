"""
Miner adapter coordinating cryptocurrency miner workloads with manual overrides and namespaced events.
"""

from __future__ import annotations

import logging
from typing import Optional

from resource_coordinator.core.events import EventDispatcher
from resource_coordinator.core.processes import ProcessInfo, ProcessSupervisor

logger = logging.getLogger(__name__)


class MinerAdapter:
    """
    Adapter bridging generic ProcessSupervisor to miner-specific concepts and events.
    """

    def __init__(
        self,
        supervisor: ProcessSupervisor,
        event_dispatcher: Optional[EventDispatcher] = None,
    ) -> None:
        self.supervisor = supervisor
        self.dispatcher = event_dispatcher or supervisor.dispatcher

        # Forward generic process events to namespaced mining events
        self.dispatcher.on("process.stopped", self._on_process_stopped)
        self.dispatcher.on("process.started", self._on_process_started)

    async def _on_process_stopped(self, event) -> None:
        if event.data.get("name") == self.supervisor.name:
            await self.dispatcher.emit("mining.stopped", event.data)

    async def _on_process_started(self, event) -> None:
        if event.data.get("name") == self.supervisor.name:
            await self.dispatcher.emit("mining.started", event.data)

    async def status(self) -> ProcessInfo:
        """Return the current process status and ownership."""
        return await self.supervisor.status()

    def set_manual_override(self, paused: bool) -> None:
        """Set manual pause override to prevent automatic restart."""
        self.supervisor.set_manual_override(paused)

    @property
    def is_manual_override(self) -> bool:
        return self.supervisor.is_manual_override

    async def pause(self, timeout: float = 10.0, origin: str = "coordinator") -> bool:
        """Request a verified miner stop."""
        await self.dispatcher.emit("mining.stop_requested", {"name": self.supervisor.name, "origin": origin})
        return await self.supervisor.stop(timeout=timeout, origin=origin)

    async def resume(self, origin: str = "coordinator", only_if_stopped_by_coordinator: bool = True) -> bool:
        """Resume mining if authorized."""
        return await self.supervisor.start(origin=origin, only_if_stopped_by_coordinator=only_if_stopped_by_coordinator)
