"""Integrations package for external service observers and notification bridges."""

from __future__ import annotations

from notifications.integrations.resource_coordinator import (
    DEFAULT_COORDINATOR_STATUS_URL,
    LockAcquisitionError,
    LockContentionError,
    LockError,
    LockSetupError,
    ObserverLock,
    RCObservation,
    ResourceCoordinatorObserver,
    get_coordinator_task_status,
    install_coordinator_task,
    uninstall_coordinator_task,
)

__all__ = [
    "DEFAULT_COORDINATOR_STATUS_URL",
    "LockAcquisitionError",
    "LockContentionError",
    "LockError",
    "LockSetupError",
    "ObserverLock",
    "RCObservation",
    "ResourceCoordinatorObserver",
    "get_coordinator_task_status",
    "install_coordinator_task",
    "uninstall_coordinator_task",
]
