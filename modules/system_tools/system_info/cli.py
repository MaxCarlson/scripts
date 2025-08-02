#!/usr/bin/env python3
"""
System Info CLI

This CLI prints the maximum amount of system information by default.
It attempts to print both admin-required and non-admin info:
  - If admin privileges are available, it prints all info.
  - Otherwise, it warns the user and prints only non-admin info.

It automatically detects the OS and calls the appropriate functions from:
  - windows_info.py, linux_info.py, mac_info.py, termux_info.py.
  
Command-line flags allow overriding behavior.
"""

import argparse
import sys
from system_tools.core.system_utils import SystemUtils
from system_tools.standard_ui import log_info, log_warning, log_error  # assuming standard_ui is re-exported in __init__.py of system_tools
from . import windows_info, linux_info, mac_info, termux_info

def main():
    parser = argparse.ArgumentParser(
        description="Extensive System Information CLI"
    )
    parser.add_argument("--admin-mode", "-a", action="store_true",
                        help="Force execution in admin mode.")
    parser.add_argument("--nonadmin-mode", "-n", action="store_true",
                        help="Force execution in non-admin mode (some info may be omitted).")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose logging output.")

    # Section filters
    parser.add_argument("--os", "-o", action="store_true",
                        help="Show only OS information.")
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

    # Build section flags dictionary:
    section_flags = {"os": args.os, "bios": args.bios, "cpu": args.cpu,
                     "memory": args.memory, "gpu": args.gpu,
                     "drives": args.drives, "network": args.network}
    # If no section flag is provided, show all
    if not any(section_flags.values()):
        section_flags = {key: True for key in section_flags}

    sys_utils = SystemUtils()

    # Determine admin mode
    if args.nonadmin_mode:
        admin_mode = False
    elif args.admin_mode or sys_utils.is_admin():
        admin_mode = True
    else:
        log_warning("Admin privileges are not available; falling back to non-admin mode.")
        admin_mode = False

    log_info("Gathering system information...")

    # Dispatch to the appropriate OS-specific module:
    if sys_utils.os_name == "windows":
        windows_info.get_windows_info(section_flags, sys_utils, admin_mode)
    elif sys_utils.os_name == "linux":
        if sys_utils.is_termux():
            termux_info.get_termux_info(section_flags, sys_utils, admin_mode)
        else:
            linux_info.get_linux_info(section_flags, sys_utils, admin_mode)
    elif sys_utils.is_mac():
        mac_info.get_mac_info(section_flags, sys_utils, admin_mode)
    else:
        log_error(f"Unsupported OS: {sys_utils.os_name}")
        sys.exit(1)

if __name__ == "__main__":
    main()
