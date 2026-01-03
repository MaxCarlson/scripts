"""Path normalization helpers shared across scripts."""

from __future__ import annotations

import os
from pathlib import PureWindowsPath
from typing import Optional

from .system_utils import SystemUtils


def expand_path(value: str) -> str:
    """
    Expand environment variables and the user home directory.

    When expansion fails or produces an empty string, the original value is returned.
    """
    if value is None:
        return ""
    expanded = os.path.expandvars(os.path.expanduser(value))
    return expanded or value


def _looks_like_windows_drive(path_str: str) -> bool:
    return len(path_str) >= 2 and path_str[1] == ":" and path_str[0].isalpha()


def to_posix_path(value: str) -> str:
    """
    Convert any path (including Windows paths) into a POSIX-style string.

    This keeps glob characters intact and is ideal when passing arguments to tools
    like ripgrep that expect forward slashes even on Windows.
    """
    candidate = expand_path(value)
    if not candidate:
        return candidate
    if candidate.startswith("\\\\"):
        # UNC path
        return candidate.replace("\\", "/")
    if _looks_like_windows_drive(candidate):
        try:
            return PureWindowsPath(candidate).as_posix()
        except Exception:
            return candidate.replace("\\", "/")
    return candidate.replace("\\", "/")


def to_native_path(value: str, system: Optional[SystemUtils] = None) -> str:
    """
    Convert a path string into the current platform's preferred separator style.

    On Windows this yields backslashes, while Unix platforms receive forward slashes.
    """
    candidate = expand_path(value)
    if not candidate:
        return candidate
    if system is None:
        system = SystemUtils()
    if system.is_windows():
        return candidate.replace("/", "\\")
    # Unix-like environments generally accept forward slashes
    return candidate.replace("\\", "/")


__all__ = ["expand_path", "to_posix_path", "to_native_path"]
