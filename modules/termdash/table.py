#!/usr/bin/env python3
"""
TermDash Table component — ANSI-aware, column-aligned terminal tables.
"""

from __future__ import annotations

import re
import shutil
import unicodedata
from typing import Any, Iterable, Literal, Sequence

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

Alignment = Literal["left", "right", "center"]


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", str(s or ""))


def _visible_len(s: str) -> int:
    return sum(_char_width(char) for char in _strip_ansi(s))


def _char_width(char: str) -> int:
    if unicodedata.combining(char) or unicodedata.category(char).startswith("C"):
        return 0
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def _pad_cell(text: str, width: int, align: Alignment = "left") -> str:
    """Pad string to target visual width while preserving inner ANSI codes."""
    vis_len = _visible_len(text)
    diff = max(0, width - vis_len)
    if diff == 0:
        return text

    if align == "right":
        return (" " * diff) + text
    elif align == "center":
        left = diff // 2
        right = diff - left
        return (" " * left) + text + (" " * right)
    else:  # left
        return text + (" " * diff)


def _truncate_cell(text: str, max_chars: int) -> str:
    """Truncate string to visual length max_chars, appending '…' if clipped."""
    if max_chars <= 0:
        return ""
    if _visible_len(text) <= max_chars:
        return text

    # Strip ANSI or truncate carefully if needed
    plain = _strip_ansi(text)
    if len(plain) <= max_chars:
        return text
    result = []
    used = 0
    for char in plain:
        used += _char_width(char)
        if used > max_chars - 1:
            break
        result.append(char)
    return "".join(result) + "…"


# Border presets
_BORDERS = {
    "rule": {
        "top_left": "┌",
        "top_right": "┐",
        "bottom_left": "└",
        "bottom_right": "┘",
        "h": "─",
        "v": "│",
        "cross": "┼",
        "t_down": "┬",
        "t_up": "┴",
        "t_right": "├",
        "t_left": "┤",
    },
    "dash": {
        "top_left": "+",
        "top_right": "+",
        "bottom_left": "+",
        "bottom_right": "+",
        "h": "-",
        "v": "|",
        "cross": "+",
        "t_down": "+",
        "t_up": "+",
        "t_right": "+",
        "t_left": "+",
    },
    "ascii": {
        "top_left": "+",
        "top_right": "+",
        "bottom_left": "+",
        "bottom_right": "+",
        "h": "-",
        "v": "|",
        "cross": "+",
        "t_down": "+",
        "t_up": "+",
        "t_right": "+",
        "t_left": "+",
    },
}


class Table:
    """
    Constructs an ANSI-aware, column-aligned table for terminal display.

    Parameters
    ----------
    headers : Sequence[str] | None
        Optional column header labels.
    alignments : Sequence[Alignment] | None
        Alignment for each column ('left', 'right', 'center').
    style : {'rule', 'dash', 'ascii', 'compact', 'none'}
        Border and divider styling preset.
    padding : int
        Spaces on both sides of each cell (default: 1).
    border : bool
        Whether to draw outer borders (default: True for 'rule'/'dash'/'ascii').
    """

    def __init__(
        self,
        headers: Sequence[str] | None = None,
        alignments: Sequence[Alignment] | None = None,
        style: str = "rule",
        padding: int = 1,
        border: bool = True,
    ) -> None:
        self.headers: list[str] = [str(h).replace("\n", " ").replace("\r", " ") for h in headers] if headers else []
        self.alignments: list[Alignment] = list(alignments) if alignments else []
        self.style = style.lower()
        self.padding = max(0, padding)
        self.border = border and self.style in _BORDERS
        self._rows: list[list[str]] = []

    def add_row(self, *cells: Any) -> None:
        """Add a row of cell values to the table."""
        self._rows.append([str(c).replace("\n", " ").replace("\r", " ") if c is not None else "" for c in cells])

    def add_rows(self, rows: Iterable[Sequence[Any]]) -> None:
        """Add multiple rows to the table."""
        for row in rows:
            self.add_row(*row)

    def render(self, max_width: int | None = None) -> str:
        """Render the formatted table as a multi-line string."""
        if not self.headers and not self._rows:
            return ""

        # Determine number of columns
        num_cols = len(self.headers)
        for row in self._rows:
            num_cols = max(num_cols, len(row))

        if num_cols == 0:
            return ""

        # Normalize alignments
        aligns: list[Alignment] = list(self.alignments)
        while len(aligns) < num_cols:
            aligns.append("left")

        # Normalize header length
        headers: list[str] = list(self.headers)
        while len(headers) < num_cols:
            headers.append("")

        # Normalize rows
        norm_rows: list[list[str]] = []
        for r in self._rows:
            row_copy = list(r)
            while len(row_copy) < num_cols:
                row_copy.append("")
            norm_rows.append(row_copy)

        # Compute column widths (ignoring ANSI)
        col_widths = [0] * num_cols
        if self.headers:
            for idx, h in enumerate(headers):
                col_widths[idx] = max(col_widths[idx], _visible_len(h))

        for row in norm_rows:
            for idx, cell in enumerate(row):
                col_widths[idx] = max(col_widths[idx], _visible_len(cell))

        # Check terminal width bounds if max_width is provided or requested
        term_cols = max(1, max_width if max_width is not None else shutil.get_terminal_size().columns)
        separator_width = 1 if self.border else 3
        overhead = num_cols * self.padding * 2 + (num_cols - 1) * separator_width + (2 if self.border else 0)
        if overhead + num_cols > term_cols:
            # A grid cannot fit: retain bounded readable text, not oversized borders.
            raw_rows = ([headers] if self.headers else []) + norm_rows
            return "\n".join(_truncate_cell(" | ".join(row), term_cols) for row in raw_rows)
        available = term_cols - overhead
        while sum(col_widths) > available:
            widest = max(range(num_cols), key=lambda index: col_widths[index])
            col_widths[widest] -= 1
        headers = [_truncate_cell(value, col_widths[index]) for index, value in enumerate(headers)]
        norm_rows = [[_truncate_cell(value, col_widths[index]) for index, value in enumerate(row)] for row in norm_rows]
        pad_str = " " * self.padding

        b = _BORDERS.get(self.style, _BORDERS["rule"])
        lines: list[str] = []

        if self.style in _BORDERS and self.border:
            # Top border
            top_parts = [b["h"] * (w + self.padding * 2) for w in col_widths]
            lines.append(f"{b['top_left']}{b['t_down'].join(top_parts)}{b['top_right']}")

        # Header row
        if self.headers:
            hdr_cells = [
                f"{pad_str}{_pad_cell(h, col_widths[idx], aligns[idx])}{pad_str}" for idx, h in enumerate(headers)
            ]
            sep_char = b["v"] if (self.border or self.style in _BORDERS) else " │ "
            if self.border:
                lines.append(f"{b['v']}{b['v'].join(hdr_cells)}{b['v']}")
            else:
                lines.append(sep_char.join(hdr_cells).rstrip())

            # Header separator
            if self.style in _BORDERS:
                sep_parts = [b["h"] * (w + self.padding * 2) for w in col_widths]
                if self.border:
                    lines.append(f"{b['t_right']}{b['cross'].join(sep_parts)}{b['t_left']}")
                else:
                    lines.append(f"{b['h'].join(sep_parts)}")
            elif self.style == "compact":
                lines.append("─" * sum(col_widths[i] + self.padding * 2 for i in range(num_cols)))
            elif self.style == "none":
                lines.append("-" * sum(col_widths[i] + self.padding * 2 for i in range(num_cols)))

        # Data rows
        v_sep = b["v"] if self.border else (" │ " if self.style in _BORDERS else "   ")
        for row in norm_rows:
            cells = [
                f"{pad_str}{_pad_cell(row[idx], col_widths[idx], aligns[idx])}{pad_str}" for idx in range(num_cols)
            ]
            if self.border:
                lines.append(f"{b['v']}{b['v'].join(cells)}{b['v']}")
            else:
                lines.append(v_sep.join(cells).rstrip())

        # Bottom border
        if self.style in _BORDERS and self.border:
            bot_parts = [b["h"] * (w + self.padding * 2) for w in col_widths]
            lines.append(f"{b['bottom_left']}{b['t_up'].join(bot_parts)}{b['bottom_right']}")

        return "\n".join(lines)


def render_table(
    headers: Sequence[str] | None = None,
    rows: Sequence[Sequence[Any]] | None = None,
    alignments: Sequence[Alignment] | None = None,
    style: str = "rule",
    padding: int = 1,
    border: bool = True,
    max_width: int | None = None,
) -> str:
    """Convenience helper to build and render a Table in one call."""
    t = Table(headers=headers, alignments=alignments, style=style, padding=padding, border=border)
    if rows:
        t.add_rows(rows)
    return t.render(max_width=max_width)
