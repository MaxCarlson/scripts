"""Reusable terminal-independent launch plans with a Windows Terminal backend."""

from .backend import ManagedLaunchResult
from .backends.windows_terminal import WindowsTerminalBackend
from .layouts import group_panes
from .managed import ManagedProcessRecord, ManagedProcessState, ManagedProcessStore, ShutdownRequestResult
from .models import PaneSpec, TabSpec, TerminalLaunchPlan
from .powershell import powershell_plan

__all__ = [
    "PaneSpec",
    "TabSpec",
    "TerminalLaunchPlan",
    "ManagedLaunchResult",
    "ManagedProcessRecord",
    "ManagedProcessState",
    "ManagedProcessStore",
    "ShutdownRequestResult",
    "WindowsTerminalBackend",
    "group_panes",
    "powershell_plan",
]

__version__ = "0.2.0"
