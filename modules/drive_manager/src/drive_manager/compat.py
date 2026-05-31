from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

try:
    from cross_platform.debug_utils import write_debug as _cp_write_debug
except Exception:
    _cp_write_debug = None

try:
    from cross_platform.privileges_manager import PrivilegesManager as _CpPrivilegesManager
except Exception:
    _CpPrivilegesManager = None

try:
    from cross_platform.system_utils import SystemUtils as _CpSystemUtils
except Exception:
    _CpSystemUtils = None


def write_debug(
    message: str = "",
    channel: str = "Debug",
    condition: bool = True,
    output_stream: str = "stdout",
    location_channels=None,
) -> None:
    if _cp_write_debug is not None:
        _cp_write_debug(message, channel=channel, condition=condition, output_stream=output_stream, location_channels=location_channels)
        return
    if not condition:
        return
    stream = sys.stderr if output_stream.lower() == "stderr" else sys.stdout
    print(f"[{channel}] {message}", file=stream)


class SystemUtils:
    """Small compatibility layer that delegates to cross_platform when available."""

    def __init__(self) -> None:
        self._delegate = _CpSystemUtils() if _CpSystemUtils is not None else None
        self.os_name = platform.system().lower()

    def is_windows(self) -> bool:
        if self._delegate is not None and hasattr(self._delegate, "is_windows"):
            return bool(self._delegate.is_windows())
        return self.os_name == "windows"

    def is_linux(self) -> bool:
        if self._delegate is not None and hasattr(self._delegate, "is_linux"):
            return bool(self._delegate.is_linux())
        return self.os_name == "linux"

    def is_darwin(self) -> bool:
        if self._delegate is not None and hasattr(self._delegate, "is_darwin"):
            return bool(self._delegate.is_darwin())
        return self.os_name == "darwin"

    def is_wsl2(self) -> bool:
        if self._delegate is not None and hasattr(self._delegate, "is_wsl2"):
            return bool(self._delegate.is_wsl2())
        try:
            return "microsoft" in platform.uname().release.lower()
        except Exception:
            return False

    def is_termux(self) -> bool:
        if self._delegate is not None and hasattr(self._delegate, "is_termux"):
            return bool(self._delegate.is_termux())
        return "ANDROID_ROOT" in os.environ or Path("/data/data/com.termux").exists()

    def run_command(self, command: str, sudo: bool = False, timeout_seconds: int | None = None) -> str:
        if sudo and not self.is_windows() and not command.strip().startswith("sudo "):
            command = f"sudo {command}"
        try:
            cp = subprocess.run(
                command,
                shell=True,
                check=False,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            write_debug(f"Command timed out after {timeout_seconds}s: {command}", channel="Error", output_stream="stderr")
            return (exc.stdout or "") + (exc.stderr or "")
        if cp.returncode != 0:
            write_debug(f"Command failed ({cp.returncode}): {command}\n{cp.stderr.strip()}", channel="Warning", output_stream="stderr")
        return cp.stdout


class PrivilegesManager:
    """Compatibility wrapper around cross_platform.PrivilegesManager."""

    def __init__(self) -> None:
        self._delegate = _CpPrivilegesManager() if _CpPrivilegesManager is not None else None
        self.sysu = SystemUtils()

    def is_admin(self) -> bool:
        if self._delegate is not None and hasattr(self._delegate, "is_admin"):
            return bool(self._delegate.is_admin())
        if self.sysu.is_windows():
            try:
                import ctypes
                return bool(ctypes.windll.shell32.IsUserAnAdmin())
            except Exception:
                return False
        return hasattr(os, "geteuid") and os.geteuid() == 0

    def require_admin(self) -> None:
        if self._delegate is not None and hasattr(self._delegate, "require_admin"):
            self._delegate.require_admin()
            return
        if not self.is_admin():
            raise PermissionError("Administrator/root privileges are required.")
