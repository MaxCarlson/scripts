"""
Resource Coordinator.

General-purpose event-driven resource coordination framework, process supervisor,
and LM Studio proxy gateway.
"""

__version__ = "0.3.0"

from resource_coordinator.core.events import Event, EventDispatcher, VetoOperation
from resource_coordinator.core.leases import Lease, LeaseManager, LeaseType
from resource_coordinator.core.processes import (
    FakeProcessBackend,
    ProcessBackend,
    ProcessInfo,
    ProcessState,
    ProcessSupervisor,
)

__all__ = [
    "__version__",
    "Event",
    "EventDispatcher",
    "VetoOperation",
    "Lease",
    "LeaseManager",
    "LeaseType",
    "ProcessBackend",
    "FakeProcessBackend",
    "ProcessInfo",
    "ProcessState",
    "ProcessSupervisor",
]
