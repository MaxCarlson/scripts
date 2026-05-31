from __future__ import annotations

from drive_manager.compat import SystemUtils
from drive_manager.platform_base import PlatformBackend
from drive_manager.platforms.linux import LinuxBackend
from drive_manager.platforms.windows import WindowsBackend


def get_backend() -> PlatformBackend:
    sysu = SystemUtils()
    if sysu.is_windows():
        return WindowsBackend()
    if sysu.is_linux() or sysu.is_wsl2() or sysu.is_termux():
        return LinuxBackend()
    raise RuntimeError(f"Unsupported platform for drive-manager: {sysu.os_name}")
