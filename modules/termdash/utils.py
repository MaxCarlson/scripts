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

# --- simple formatting / units / clipping ---

def fmt_hms(seconds):
    """Return HH:MM:SS (accepts float or int; None -> '--:--:--')."""
    if seconds is None:
        return "--:--:--"
    s = int(max(0, float(seconds)))
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"

def bytes_to_mib(n_bytes):
    """Convert bytes -> mebibytes (MiB) as float."""
    try:
        return float(n_bytes) / (1024.0 * 1024.0)
    except Exception:
        return 0.0

def clip_ellipsis(text: str, max_chars: int) -> str:
    """Hard-clip string to <= max_chars, adding a single-character ellipsis if clipped."""
    if max_chars <= 0:
        return text or ""
    s = str(text or "")
    return s if len(s) <= max_chars else s[:max_chars - 1] + "…"
