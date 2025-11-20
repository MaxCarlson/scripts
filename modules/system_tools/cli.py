#!/usr/bin/env python3
"""
System Information CLI

This CLI provides extensive system information for various OS types.
It automatically detects the OS and loads the appropriate module to 
display detailed hardware and software information.

----------------------------------------
Command-Line Argument Formatting Rules:
----------------------------------------
1. Every flag must have a full-length version beginning with '--' followed by a descriptive name.
   Example: --bios
2. Every flag must also have an abbreviated version using a single dash '-' followed by exactly one character.
   Example: -b (capital letters are allowed, but only one character may follow the dash).
3. Abbreviated versions cannot be combined (e.g., use '-b -c' instead of '-bc').
These rules ensure clarity and consistency when specifying command-line arguments.
"""

import argparse
import sys
import os
import ctypes

from system_tools.core.system_utils import SystemUtils
from standard_ui import log_info, log_warning, log_error

def is_admin():
    # Windows admin check uses ctypes; Linux/Mac use os.geteuid()
    if os.name == "nt":
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin()
        except Exception as e:
            log_error(f"Admin check failed: {e}")
            return False
    else:
        try:
            return os.geteuid() == 0
        except AttributeError:
            return False

def main():
    parser = argparse.ArgumentParser(
        description="Extensive System Information CLI"
    )
    parser.add_argument("--admin-mode", "-a", action="store_true",
                        help="Force execution in admin mode.")
    parser.add_argument("--nonadmin-mode", "-n", action="store_true",
                        help="Force execution in non-admin mode (may reduce available info).")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose logging output.")
    # Section filters
    parser.add_argument("--os", "-o", action="store_true",
                        help="Show only Operating System information.")
    parser.add_argument("--bios", "-b", action="store_true",
                        help="Show only BIOS/Hardware information.")
    parser.add_argument("--cpu", "-c", action="store_true",
                        help="Show only CPU information.")
    parser.add_argument("--memory", "-m", action="store_true",
                        help="Show only Memory information.")
    parser.add_argument("--gpu", "-g", action="store_true",
                        help="Show only GPU information.")
    parser.add_argument("--drives", "-d", action="store_true",
                        help="Show only Drives/Storage information.")
    parser.add_argument("--network", "-w", action="store_true",
                        help="Show only Network information.")
    args = parser.parse_args()

    # Determine which sections to display
    section_flags = ["os", "bios", "cpu", "memory", "gpu", "drives", "network"]
    if any(getattr(args, flag) for flag in section_flags):
        sections = {flag: getattr(args, flag) for flag in section_flags}
    else:
        sections = {flag: True for flag in section_flags}

    sys_utils = SystemUtils()

    # Detect OS and dispatch to the appropriate module
    if sys_utils.os_name == "windows":
        from system_tools.system_info import windows_info
        if args.nonadmin_mode:
            admin_mode = False
        elif args.admin_mode or is_admin():
            admin_mode = True
        else:
            log_warning("Admin privileges are not available; falling back to non-admin mode.")
            admin_mode = False
        log_info("Gathering Windows system information...")
        windows_info.get_windows_info(sections, sys_utils, admin_mode)
    elif sys_utils.os_name == "linux":
        if sys_utils.is_termux():
            from system_tools.system_info import termux_info
            admin_mode = False  # Termux typically runs without admin privileges
            log_info("Gathering Termux system information...")
            termux_info.get_termux_info(sections, sys_utils, admin_mode)
        else:
            from system_tools.system_info import linux_info
            if args.nonadmin_mode:
                admin_mode = False
            elif args.admin_mode or is_admin():
                admin_mode = True
            else:
                log_warning("Admin privileges are not available; falling back to non-admin mode.")
                admin_mode = False
            log_info("Gathering Linux system information...")
            linux_info.get_linux_info(sections, sys_utils, admin_mode)
    elif sys_utils.is_mac():
        from system_tools.system_info import mac_info
        admin_mode = args.admin_mode or is_admin()  # Admin less critical for macOS system_profiler
        log_info("Gathering macOS system information...")
        mac_info.get_mac_info(sections, sys_utils, admin_mode)
    else:
        log_error(f"Unsupported OS: {sys_utils.os_name}")
        sys.exit(1)

if __name__ == "__main__":
    main()
