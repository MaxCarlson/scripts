"""Reusable terminal-independent launch plans with a Windows Terminal backend."""

from .backends.windows_terminal import WindowsTerminalBackend
from .layouts import group_panes
from .models import PaneSpec, TabSpec, TerminalLaunchPlan

__all__ = [
    "PaneSpec",
    "TabSpec",
    "TerminalLaunchPlan",
    "WindowsTerminalBackend",
    "group_panes",
]

__version__ = "0.1.0"
