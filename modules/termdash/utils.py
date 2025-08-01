#!/usr/bin/env python3
"""
Utility functions for the TermDash module.
"""

def format_bytes(mib_val):
    """Formats a numeric value in MiB into a human-readable byte string."""
    if mib_val >= 1024:
        return f"{mib_val / 1024:.2f} GiB"
    if mib_val < (1/1024):
        return f"{mib_val * 1024 * 1024:.2f} B"
    if mib_val < 1:
        return f"{mib_val * 1024:.2f} KiB"
    return f"{mib_val:.2f} MiB"
