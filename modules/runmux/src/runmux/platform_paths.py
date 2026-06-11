"""Cross-platform state path helpers for runmux."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from runmux.constants import APP_NAME


def get_state_dir() -> Path:
    """Return the directory used for runmux state.

    Resolution order:
    1. ``RUNMUX_HOME`` if explicitly set.
    2. ``LOCALAPPDATA\\runmux`` on Windows.
    3. ``$XDG_STATE_HOME/runmux`` on Unix-like systems.
    4. ``~/.local/state/runmux`` fallback.
    """

    explicit_home = os.environ.get("RUNMUX_HOME")
    if explicit_home:
        return Path(explicit_home).expanduser().resolve()

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data).expanduser().resolve() / APP_NAME
        return Path.home() / "AppData" / "Local" / APP_NAME

    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home).expanduser().resolve() / APP_NAME

    return Path.home() / ".local" / "state" / APP_NAME


def ensure_state_tree(state_dir: Path | None = None) -> Path:
    """Create and return the state directory tree."""

    root = state_dir or get_state_dir()
    root.mkdir(parents=True, exist_ok=True)
    (root / "runs").mkdir(parents=True, exist_ok=True)
    return root
