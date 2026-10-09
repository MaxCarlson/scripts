"""
Scheduler module: robust Python scheduling, automation, and command execution.
"""
from __future__ import annotations

__version__ = "0.6.0"

from .models import Schedule, ScheduleTiming, Task, ExecutionResult, TimingType
from .config import ConfigManager
from .storage import StorageManager
from .timing import calculate_next_run, is_missed_run
from .executor import TaskExecutor
from .logger import CentralLogger, TaskLogger
from .notifier import Notifier
from .service import SchedulerService

__all__ = [
    "__version__",
    "Schedule",
    "ScheduleTiming",
    "Task",
    "ExecutionResult",
    "TimingType",
    "ConfigManager",
    "StorageManager",
    "calculate_next_run",
    "is_missed_run",
    "TaskExecutor",
    "CentralLogger",
    "TaskLogger",
    "Notifier",
    "SchedulerService",
]
