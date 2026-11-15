"""Event-driven collectors for ProcWatch."""

from procwatch.collectors.sysmon_evt import SysmonCollector
from procwatch.collectors.task_events import TaskSchedulerCollector
from procwatch.collectors.win_event import WinEventCollector
from procwatch.collectors.wmi_trace import WmiProcessEvent, WmiProcessTraceCollector

__all__ = [
    "SysmonCollector",
    "TaskSchedulerCollector",
    "WinEventCollector",
    "WmiProcessEvent",
    "WmiProcessTraceCollector",
]
