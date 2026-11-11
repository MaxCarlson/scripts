"""Read-only adapters package."""

from remote_control.adapters.heartbeat_adapter import ReadOnlyMonitoringAdapter
from remote_control.adapters.notifications_adapter import ReadOnlyNotificationsAdapter

__all__ = [
    "ReadOnlyMonitoringAdapter",
    "ReadOnlyNotificationsAdapter",
]
