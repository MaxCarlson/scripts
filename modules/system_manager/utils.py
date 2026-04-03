#!/usr/bin/env python3
"""
Utility functions for System Manager.
"""

import base64
import shutil
from cross_platform import SystemUtils

sysu = SystemUtils()

def run_powershell(script: str) -> str:
    """
    Run a PowerShell script using Base64 encoding to avoid cmd.exe parsing issues.
    """
    ps_exe = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
    # Convert script to UTF-16LE bytes as required by PowerShell -EncodedCommand
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    # Use -NoProfile and -NonInteractive for robustness
    cmd = f'"{ps_exe}" -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand {encoded}'
    return sysu.run_command(cmd)

def get_console_width() -> int:
    """Return the current console width."""
    try:
        return shutil.get_terminal_size().columns
    except:
        return 80

def get_console_height() -> int:
    """Return the current console height."""
    try:
        return shutil.get_terminal_size().lines
    except:
        return 24
