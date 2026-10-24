"""
tui.py — Terminal rendering and formatted presentation for SQLite inspection and browsing.
"""

from __future__ import annotations

from typing import Any


def format_table(
    headers: list[str],
    rows: list[list[str]],
    max_col_width: int = 40,
    title: str | None = None,
) -> str:
    """
    Renders a formatted ASCII table with headers and data rows.
    Dynamically adjusts column widths based on terminal dimensions.
    """
    if not headers and not rows:
        return "(empty table)"

    # Determine column widths
    num_cols = len(headers) if headers else (len(rows[0]) if rows else 0)
    col_widths = [len(h) for h in headers] if headers else [0] * num_cols

    for row in rows:
        for i in range(min(num_cols, len(row))):
            col_widths[i] = max(col_widths[i], len(row[i]))

    # Cap column widths
    col_widths = [min(w, max_col_width) for w in col_widths]

    def _truncate(val: str, width: int) -> str:
        if len(val) > width:
            return val[: width - 3] + "..." if width >= 3 else val[:width]
        return val.ljust(width)

    lines: list[str] = []

    if title:
        lines.append(f"=== {title} ===")

    # Top border
    sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    lines.append(sep)

    # Headers
    if headers:
        header_line = "|" + "|".join(f" {_truncate(headers[i], col_widths[i])} " for i in range(num_cols)) + "|"
        lines.append(header_line)
        lines.append(sep)

    # Data rows
    for row in rows:
        padded_row = list(row) + [""] * (num_cols - len(row))
        row_line = "|" + "|".join(f" {_truncate(padded_row[i], col_widths[i])} " for i in range(num_cols)) + "|"
        lines.append(row_line)

    lines.append(sep)
    return "\n".join(lines)


def format_key_values(pairs: list[tuple[str, Any]], title: str | None = None) -> str:
    """Renders key-value metadata in a clean two-column format."""
    lines: list[str] = []
    if title:
        lines.append(f"=== {title} ===")

    max_key_len = max((len(k) for k, _ in pairs), default=15)
    for key, val in pairs:
        lines.append(f"  {key.ljust(max_key_len)} : {val}")

    return "\n".join(lines)
