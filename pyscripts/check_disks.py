#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
A cross-platform script to check disk usage on both Windows (via PowerShell)
and Unix-like systems (Linux, macOS, Termux) using df.

Supports a concise output mode for Unix-like systems.
"""

import argparse
import json
import platform
import subprocess
import sys
from typing import Any, Dict, List, Optional

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Check disk usage on Windows, Linux, macOS, or Termux.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "-c", "--concise",
        action="store_true",
        help="Show a concise summary for Unix-like systems.\n(e.g., on Termux, shows only root and user storage)"
    )
    return parser.parse_args(argv)

def format_bytes(byte_count: Optional[int]) -> str:
    """Converts a byte count into a human-readable string (KB, MB, GB, etc.)."""
    if not isinstance(byte_count, (int, float)):
        return "N/A"
    if byte_count < 0:
        return "N/A"
    if byte_count == 0:
        return "0 B"
    
    power = 1024
    n = 0
    power_labels = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    while byte_count >= power and n < len(power_labels) - 1:
        byte_count /= power
        n += 1
        
    # Format to 1 decimal place if it's not a whole number, otherwise show as integer
    if n > 0 and byte_count != int(byte_count):
        return f"{byte_count:.1f} {power_labels[n]}"
    return f"{int(byte_count)} {power_labels[n]}"


def print_table(headers: List[str], data: List[List[Any]]):
    """Prints a list of lists as a formatted table."""
    if not data:
        print("No data to display.")
        return

    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in data:
        for i, cell in enumerate(row):
            if len(str(cell)) > col_widths[i]:
                col_widths[i] = len(str(cell))

    # Print header
    header_line = " | ".join(f"{h:<{col_widths[i]}}" for i, h in enumerate(headers))
    print(header_line)
    
    # Print separator
    separator_line = "-|-".join("-" * width for width in col_widths)
    print(separator_line)

    # Print data rows
    for row in data:
        data_line = " | ".join(f"{str(c):<{col_widths[i]}}" for i, c in enumerate(row))
        print(data_line)

def check_disk_usage_windows():
    """
    Retrieves disk usage on Windows using PowerShell.
    Fetches data as JSON for reliable parsing.
    """
    print("Detected Windows. Using PowerShell to get disk usage...\n")
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-PSDrive | Where-Object { $_.Provider -eq 'FileSystem' } | Select-Object Name, @{N='Total';E={$_.Used + $_.Free}}, Used, Free | ConvertTo-Json"
    ]
    
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
        drives_json_str = result.stdout.strip()
        
        # If there's only one drive, ConvertTo-Json returns a single object.
        # If multiple, it returns an array. We normalize to an array.
        if drives_json_str and not drives_json_str.startswith('['):
            drives_json_str = f"[{drives_json_str}]"
            
        drives = json.loads(drives_json_str) if drives_json_str else []
        
        headers = ["Drive", "Total", "Used", "Free", "Use%"]
        table_data = []

        for drive in drives:
            total_bytes = drive.get('Total')
            used_bytes = drive.get('Used')
            
            if total_bytes is not None and used_bytes is not None and total_bytes > 0:
                percent_used = (used_bytes / total_bytes) * 100
                percent_str = f"{percent_used:.0f}%"
            else:
                percent_str = "N/A"

            table_data.append([
                drive.get('Name'),
                format_bytes(total_bytes),
                format_bytes(used_bytes),
                format_bytes(drive.get('Free')),
                percent_str
            ])
        
        print_table(headers, table_data)

    except FileNotFoundError:
        print("Error: 'powershell' command not found. Is PowerShell installed and in your PATH?", file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"Error executing PowerShell command:\n{e.stderr}", file=sys.stderr)
    except json.JSONDecodeError:
        print(f"Error parsing JSON from PowerShell output:\n{result.stdout}", file=sys.stderr)


def check_disk_usage_nix(concise: bool = False):
    """
    Retrieves disk usage on Unix-like systems (Linux, macOS, Termux) using 'df'.
    """
    print("Detected Unix-like OS. Using 'df' to get disk usage...\n")
    # -k: sizes in 1024-byte blocks
    # -P: POSIX format to prevent line wrapping, ensuring stable parsing
    command = ["df", "-kP"]
    
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
        lines = result.stdout.strip().split('\n')
        
        headers = ["Filesystem", "Total", "Used", "Available", "Use%", "Mounted on"]
        all_data = []

        # Skip the header line from the df output
        for line in lines[1:]:
            parts = line.split()
            
            if len(parts) < 6:
                continue # Skip malformed lines
            
            # Handle cases where mount points might have spaces
            if len(parts) > 6:
                parts = parts[:5] + [" ".join(parts[5:])]

            filesystem, total_kb, used_kb, avail_kb, use_percent, mount = parts
            
            all_data.append([
                filesystem,
                format_bytes(int(total_kb) * 1024),
                format_bytes(int(used_kb) * 1024),
                format_bytes(int(avail_kb) * 1024),
                use_percent,
                mount
            ])
        
        if concise:
            # Filter for Termux-relevant mount points
            concise_mounts = {"/", "/storage/emulated"}
            table_data = [row for row in all_data if row[5] in concise_mounts]
        else:
            table_data = all_data
            
        print_table(headers, table_data)

    except FileNotFoundError:
        print("Error: 'df' command not found. This is unexpected on a Unix-like system.", file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"Error executing 'df' command:\n{e.stderr}", file=sys.stderr)
    except (ValueError, IndexError) as e:
        print(f"Error parsing 'df' output: {e}\nPlease check the command output:\n{result.stdout}", file=sys.stderr)


def main():
    """
    Main function to detect the OS and run the appropriate disk check.
    """
    args = parse_args()
    os_type = platform.system()
    
    if os_type == "Windows":
        check_disk_usage_windows()
    elif os_type in ["Linux", "Darwin"]:
        check_disk_usage_nix(concise=args.concise)
    else:
        print(f"Unsupported OS: {os_type}", file=sys.stderr)
        print("Attempting to use Unix 'df' command as a fallback...", file=sys.stderr)
        check_disk_usage_nix(concise=args.concise)

if __name__ == "__main__":
    main()
