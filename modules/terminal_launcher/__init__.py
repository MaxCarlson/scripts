"""Reusable terminal-independent launch plans with a Windows Terminal backend."""

from .backend import ManagedLaunchResult
from .backends.windows_terminal import WindowsTerminalBackend
from .layouts import group_panes
from .managed import (
    InterruptionState,
    LaunchSubmissionState,
    ManagedPaneReservation,
    ManagedProcessRecord,
    ManagedProcessState,
    ManagedProcessStore,
    ProcessLiveness,
    ShutdownRequestResult,
)
from .models import PaneSpec, TabSpec, TerminalLaunchPlan
from .powershell import powershell_plan

__all__ = [
    "PaneSpec",
    "TabSpec",
    "TerminalLaunchPlan",
    "ManagedLaunchResult",
    "LaunchSubmissionState",
    "ManagedPaneReservation",
    "ManagedProcessRecord",
    "ManagedProcessState",
    "ManagedProcessStore",
    "ProcessLiveness",
    "InterruptionState",
    "ShutdownRequestResult",
    "WindowsTerminalBackend",
    "group_panes",
    "powershell_plan",
]

__version__ = "0.2.0"
