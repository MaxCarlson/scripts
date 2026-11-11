"""Integrations package for external service observers and notification bridges."""

from __future__ import annotations

from notifications.integrations.resource_coordinator import (
    RCObservation,
    ResourceCoordinatorObserver,
)

__all__ = ["RCObservation", "ResourceCoordinatorObserver"]
