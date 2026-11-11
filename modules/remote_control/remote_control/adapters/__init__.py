"""Read-only adapters package."""

from remote_control.adapters.coordinator_adapter import ReadOnlyCoordinatorAdapter
from remote_control.adapters.heartbeat_adapter import ReadOnlyMonitoringAdapter
from remote_control.adapters.notifications_adapter import ReadOnlyNotificationsAdapter

__all__ = [
    "ReadOnlyCoordinatorAdapter",
    "ReadOnlyMonitoringAdapter",
    "ReadOnlyNotificationsAdapter",
]
