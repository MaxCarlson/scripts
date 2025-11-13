from __future__ import annotations

"""
Cross-platform size parsing and formatting helpers.

- parse_size_to_bytes: parse strings like "500M", "2G", "1024" into an int byte count.
- format_bytes_binary: format bytes using binary units (KiB, MiB, GiB, TiB).

These functions avoid any external dependencies and are safe to re-use across modules.
"""

from typing import Optional


_UNIT_MAP = {
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
    "t": 1024**4,
    "tb": 1024**4,
}


def parse_size_to_bytes(raw: Optional[str]) -> Optional[int]:
    """
    Parse a human-friendly size string into bytes.

    Accepted forms (case-insensitive):
    - "123" -> 123 bytes
    - "500M", "500MB"
    - "2G", "2GB"
    - "1T", "1TB"
    - "64K", "64KB"

    Returns None if input is None or empty.
    Raises ValueError on invalid input.
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None

    # Separate number and unit
    i = 0
    n = len(s)
    while i < n and (s[i].isdigit() or s[i] in ".,"):
        i += 1
    num_str = s[:i].replace(",", "")
    unit_str = s[i:].strip().lower()

    try:
        value = float(num_str) if num_str else 0.0
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Invalid size value: {raw}") from e

    if not unit_str:
        return int(value)

    if unit_str not in _UNIT_MAP:
        raise ValueError(f"Unknown size unit in '{raw}'; expected one of K, M, G, T (optional 'B').")
    return int(value * _UNIT_MAP[unit_str])


def format_bytes_binary(num_bytes: int) -> str:
    """
    Format a byte count using binary units with two decimals.

    Examples:
        0 -> "0 B"
        1024 -> "1.00 KiB"
        1048576 -> "1.00 MiB"
    """
    value = float(num_bytes)
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    idx = 0
    while value >= 1024.0 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    if units[idx] == "B":
        return f"{int(value)} {units[idx]}"
    return f"{value:.2f} {units[idx]}"

