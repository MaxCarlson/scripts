"""Event-driven collectors for ProcWatch."""

from procwatch.collectors.win_event import WinEventCollector
from procwatch.collectors.wmi_trace import WmiProcessEvent, WmiProcessTraceCollector

__all__ = [
    "WinEventCollector",
    "WmiProcessEvent",
    "WmiProcessTraceCollector",
]
