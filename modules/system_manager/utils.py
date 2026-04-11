#!/usr/bin/env python3
"""
Utility functions for System Manager.
"""

import shutil
from cross_platform import SystemUtils, run_powershell_text

sysu = SystemUtils()

def run_powershell(script: str) -> str:
    """
    Run a PowerShell script using Base64 encoding to avoid cmd.exe parsing issues.
    """
    return run_powershell_text(script)

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
