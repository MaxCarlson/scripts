"""Integrations package for external service observers and notification bridges."""

from __future__ import annotations

from notifications.integrations.resource_coordinator import (
    LockAcquisitionError,
    ObserverLock,
    RCObservation,
    ResourceCoordinatorObserver,
    get_coordinator_task_status,
    install_coordinator_task,
    uninstall_coordinator_task,
)

__all__ = [
    "LockAcquisitionError",
    "ObserverLock",
    "RCObservation",
    "ResourceCoordinatorObserver",
    "get_coordinator_task_status",
    "install_coordinator_task",
    "uninstall_coordinator_task",
]
