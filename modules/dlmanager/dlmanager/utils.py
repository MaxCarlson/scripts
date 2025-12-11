#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shared utilities for dlmanager.
"""
from __future__ import annotations

import os
import platform
import shutil
import time
from pathlib import Path
from typing import Optional, Iterable

HOME = Path.home()
RUNTIME_DIR = HOME / ".dlmanager"
QUEUE_DIR = RUNTIME_DIR / "queue"
LOGS_DIR = RUNTIME_DIR / "logs"
STATE_DIR = RUNTIME_DIR / "state"
PID_FILE = RUNTIME_DIR / "manager.pid"


def ensure_runtime_dirs() -> Path:
    for d in (RUNTIME_DIR, QUEUE_DIR, LOGS_DIR, STATE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    return RUNTIME_DIR


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def which_or_none(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def looks_like_windows_path(value: str) -> bool:
    """Return True if the string resembles a Windows path such as 'C:\\Temp'."""
    if not value or len(value) < 3:
        return False
    if value.startswith("\\\\"):  # UNC path
        return True
    drive, sep = value[0], value[1:3]
    return drive.isalpha() and sep in (":\\", ":/")


def is_remote_spec(value: str) -> bool:
    """
    Detect whether the destination spec refers to a remote host.
    Treat rclone remotes and user@host targets as remote, but Windows drive letters
    and UNC paths remain local.
    """
    if not value:
        return False
    if value.startswith("rclone:"):
        return True
    if looks_like_windows_path(value):
        return False
    if value.startswith(("/", ".")):
        return False
    return "@" in value or (":" in value and not value.startswith("./") and not value.startswith("../"))


def is_local_transfer(spec: Optional[dict]) -> bool:
    """Return True when the destination resolves to a local filesystem path."""
    if not spec:
        return True
    return not is_remote_spec(spec.get("dst", ""))


def resolve_local_target(spec: dict) -> Path:
    """
    Resolve the concrete destination path for a local transfer.
    When dst refers to a host, dst_path must be provided. Otherwise dst is used.
    """
    dst = spec.get("dst", "")
    dst_path = spec.get("dst_path")
    if is_remote_spec(dst):
        if not dst_path or dst_path in ("~", ""):
            raise ValueError("Local transfer requested but destination path was not provided.")
        return Path(dst_path).expanduser()
    if dst_path and dst_path not in ("~", "", None):
        return Path(dst_path).expanduser()
    if not dst:
        raise ValueError("Destination must be supplied for local transfers.")
    return Path(dst).expanduser()


def _dedupe(seq: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in seq:
        if item not in seen:
            ordered.append(item)
            seen.add(item)
    return ordered


def method_order_by_preference(spec: Optional[dict] = None) -> list[str]:
    """
    Preference order for 'auto' method selection.
    Tuned for reliability and resumability and aware of destination platform hints.
    """
    spec = spec or {}
    dst_os = spec.get("dst_os", "auto")
    remote = not is_local_transfer(spec)

    order: list[str] = []

    rsync_available = bool(which_or_none("rsync"))
    # Skip rsync for remote Windows hosts without Cygwin support.
    if rsync_available:
        if not remote or dst_os in ("auto", "linux", "darwin", "termux", "wsl", "windows-cygwin"):
            order.append("rsync")

    if which_or_none("rclone"):
        order.append("rclone")

    # Native (robocopy/python) works best for local moves/copies.
    if not remote:
        order.append("native")

    if which_or_none("scp") and remote:
        order.append("scp")

    # Always fall back to native copy/move as a last resort.
    order.append("native")

    return _dedupe(order)


def guess_local_platform() -> str:
    """
    Return a coarse platform tag: 'termux', 'wsl', 'linux', 'windows', 'darwin'
    """
    sys_plat = sysname()
    if "Android" in platform.platform() or "com.termux" in str(HOME):
        return "termux"
    if "microsoft" in platform.uname().release.lower():
        return "wsl"
    if sys_plat == "Windows":
        return "windows"
    if sys_plat == "Darwin":
        return "darwin"
    return "linux"


def sysname() -> str:
    return platform.system()


def normalize_path_for_remote(path: str, dst_os: str) -> str:
    """
    Normalize destination path depending on target OS/runtime.
    - windows-cygwin: transform 'C:\\Users\\Me\\Downloads' -> '/cygdrive/c/Users/Me/Downloads'
    - windows-native: leave Windows form for native tools (e.g., rclone on Windows).
    - linux/termux: return original; tilde is okay (remote shell expands).
    """
    p = path
    if dst_os == "auto":
        return p
    if dst_os == "windows-cygwin":
        # If looks like C:\path\to\file, rewrite.
        if len(p) >= 3 and p[1:3] == ":\\" and p[0].isalpha():
            drive = p[0].lower()
            rest = p[3:].replace("\\", "/")
            return f"/cygdrive/{drive}/{rest}"
        # Support forward-slash Windows drive
        if len(p) >= 3 and p[1:3] == ":/" and p[0].isalpha():
            drive = p[0].lower()
            rest = p[3:]
            return f"/cygdrive/{drive}/{rest}"
    # For others, return as-is
    return p
