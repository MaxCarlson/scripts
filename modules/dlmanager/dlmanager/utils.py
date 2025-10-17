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
from typing import Optional

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


def method_order_by_preference() -> list[str]:
    """
    Preference order for 'auto' method selection.
    Tuned for reliability and resumability.
    """
    order: list[str] = []
    # rsync preferred if available
    if which_or_none("rsync"):
        order.append("rsync")
    # rclone next
    if which_or_none("rclone"):
        order.append("rclone")
    # scp as last resort
    if which_or_none("scp"):
        order.append("scp")
    return order


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
