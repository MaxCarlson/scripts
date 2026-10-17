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


_ANSI_OR_CHAR = re.compile(r"(\x1b\[[0-9;]*m)|(.)", re.DOTALL)


def _truncate_cell(text: str, max_chars: int) -> str:
    """Truncate string to visual length max_chars, appending '…' if clipped, preserving ANSI styling."""
    if max_chars <= 0:
        return ""
    if _visible_len(text) <= max_chars:
        return text

    has_ansi = bool(_ANSI_RE.search(text))
    result = []
    used = 0
    target_limit = max_chars - 1
    for match in _ANSI_OR_CHAR.finditer(text):
        ansi_seq, char = match.groups()
        if ansi_seq:
            result.append(ansi_seq)
            continue
        w = _char_width(char)
        if used + w > target_limit:
            break
        used += w
        result.append(char)
    result.append("…")
    if has_ansi:
        result.append("\x1b[0m")
    return "".join(result)


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


def wrap_display_text(text: str, width: int) -> list[str]:
    """Wrap full cells at word boundaries, preserving SGR style and Unicode."""
    width = max(2, width)
    lines, current, active = [], [], []
    used = 0

    def flush():
        nonlocal current, used
        lines.append("".join(current).rstrip() + ("\x1b[0m" if active else ""))
        current, used = list(active), 0

    for word in re.findall(r"\S+|\s+", str(text)):
        if not word.isspace() and used and _visible_len(word) <= width and used + _visible_len(word) > width:
            flush()
        for match in _ANSI_OR_CHAR.finditer(word):
            ansi, char = match.groups()
            if ansi:
                active = [] if ansi in ("\x1b[0m", "\x1b[m") else active + [ansi]
                current.append(ansi)
                continue
            if char == "\n":
                flush()
                continue
            if unicodedata.category(char).startswith("C"):
                char = repr(char)[1:-1]
            for token in char:
                size = _char_width(token)
                if used + size > width:
                    flush()
                if token == " " and not used:
                    continue
                current.append(token)
                used += size
    if current or not lines:
        lines.append("".join(current) + ("\x1b[0m" if active else ""))
    return lines


def render_table_panels(headers, rows, *, identity_columns=(0,), alignments=None, max_width: int) -> list[str]:
    """Opt-in lossless column panels; fall back to wrapped records if a panel cannot fit."""
    width = max(2, max_width)
    headers = [str(h) for h in headers]
    rows = [[str(c) if c is not None else "—" for c in row] for row in rows]
    if any(len(row) != len(headers) for row in rows):
        raise ValueError("Panel rows must match headers")
    identity = list(identity_columns)
    if len(set(identity)) != len(identity) or any(i < 0 or i >= len(headers) for i in identity):
        raise ValueError("Invalid identity columns")
    lengths = [max([_visible_len(h)] + [_visible_len(row[i]) for row in rows]) for i, h in enumerate(headers)]

    def fits(indices):
        return sum(lengths[i] for i in indices) + 3 * len(indices) + 1 <= width

    remaining = [i for i in range(len(headers)) if i not in identity]
    if not fits(identity) or (remaining and sum(lengths[i] for i in identity) + 3 * (len(identity) + 1) + 5 > width):
        records = []
        for number, row in enumerate(rows, 1):
            records.extend(wrap_display_text(f"Record {number}", width))
            for h, cell in zip(headers, row):
                records.extend(wrap_display_text(f"{h}:", width))
                records.extend(wrap_display_text(cell, width))
            records.append("")
        return ["\n".join(records)]
    groups, current = [], list(identity)
    for index in remaining:
        if not fits(current + [index]) and current != identity:
            groups.append(current)
            current = list(identity)
        current.append(index)
    if current:
        groups.append(current)
    panels = []
    for group in groups:
        sizes = {i: lengths[i] for i in group}
        available = width - (3 * len(group) + 1)
        while sum(sizes.values()) > available:
            adjustable = [i for i in group if i not in identity]
            largest = max(adjustable, key=lambda i: sizes[i])
            sizes[largest] -= 1

        def rule(left, middle, right):
            return left + middle.join("─" * (sizes[i] + 2) for i in group) + right

        def physical(row):
            cells = [wrap_display_text(row[i], sizes[i]) for i in group]
            output = []
            for line in range(max(map(len, cells))):
                output.append(
                    "│"
                    + "│".join(
                        " "
                        + _pad_cell(
                            cell[line] if line < len(cell) else "", sizes[i], alignments[i] if alignments else "left"
                        )
                        + " "
                        for i, cell in zip(group, cells)
                    )
                    + "│"
                )
            return output

        rendered = [rule("┌", "┬", "┐"), *physical(headers), rule("├", "┼", "┤")]
        for row in rows:
            rendered.extend(physical(row))
        rendered.append(rule("└", "┴", "┘"))
        panels.append("\n".join(rendered))
    return panels
