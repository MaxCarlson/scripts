#!/usr/bin/env python3
from __future__ import annotations

import math
import shutil
from typing import Callable, Optional, Tuple, Union

from .components import Stat


CharSet = Tuple[str, str]  # (fill, empty)


def _term_cols(default: int = 80) -> int:
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return default


class ProgressBar:
    """
    Fixed or full-width textual progress bar that plugs into a Line as a Stat.

    - Can be bound to functions returning (current, total) so it always
      reflects the *actual* progress at render time.
    - Uses no_expand=True so it won't distort column alignment.
    - Full-width mode draws a bar that spans the entire terminal width
      (useful for "bar below the row" layouts).

    Parameters
    ----------
    name : str
        Unique stat name.
    total : float | int
        Total units of work.
    current : float | int
        Starting units completed.
    width : int
        Bar width when full_width=False (includes the [..] brackets).
    charset : {"block", "ascii"} or CharSet
        "block" -> ("█", "·"), "ascii" -> ("#", "-"), or a tuple (fill, empty).
    show_percent : bool
        Overlay a centered "xx%" in the bar.
    full_width : bool
        If True, bar spans the terminal width (computed on render).
    margin : int
        Horizontal margin to subtract from terminal width in full_width mode.
    """

    def __init__(
        self,
        name: str,
        total: Union[int, float],
        current: Union[int, float] = 0,
        *,
        width: int = 30,
        charset: Union[str, CharSet] = "block",
        show_percent: bool = True,
        full_width: bool = False,
        margin: int = 2,
    ) -> None:
        self.name = name
        self._total = max(0.0, float(total))
        self._current = max(0.0, float(current))
        self.width = max(6, int(width))
        self.show_percent = bool(show_percent)
        self.full_width = bool(full_width)
        self.margin = max(0, int(margin))

        if isinstance(charset, tuple):
            self.fill_char, self.empty_char = charset
        elif charset == "ascii":
            self.fill_char, self.empty_char = "#", "-"
        else:
            # Use a high-contrast empty so "0%" isn't invisible.
            self.fill_char, self.empty_char = "█", "·"

        # Stat that renders this bar; value is `self` so Stat->format->str(self)
        self._stat = Stat(
            name,
            value=self,
            format_string="{}",
            no_expand=True,  # never push column widths
            display_width=None,  # let the string carry its own width
        )
        # Optional live bindings
        self._current_fn: Optional[Callable[[], float]] = None
        self._total_fn: Optional[Callable[[], float]] = None

    # --------------- public API ----------------

    def cell(self) -> Stat:
        """Return the Stat to insert in a Line."""
        return self._stat

    def bind(
        self,
        *,
        current_fn: Optional[Callable[[], Union[int, float]]] = None,
        total_fn: Optional[Callable[[], Union[int, float]]] = None,
    ) -> None:
        self._current_fn = (lambda: float(current_fn())) if current_fn else None
        self._total_fn = (lambda: float(total_fn())) if total_fn else None

    def set_total(self, total: Union[int, float]) -> None:
        self._total = max(0.0, float(total))

    def set(self, current: Union[int, float]) -> None:
        self._current = max(0.0, float(current))

    def advance(self, delta: Union[int, float] = 1) -> None:
        self._current = max(0.0, self._current + float(delta))

    def percent(self) -> float:
        t = self._total_fn() if self._total_fn else self._total
        c = self._current_fn() if self._current_fn else self._current
        if t <= 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * (c / t)))

    # -------------- rendering core -------------

    def __str__(self) -> str:
        """Build the bar string every time the Stat is rendered."""
        t = self._total_fn() if self._total_fn else self._total
        c = self._current_fn() if self._current_fn else self._current
        t = max(0.0, float(t))
        c = max(0.0, float(c))

        pct = 0.0 if t <= 0 else max(0.0, min(1.0, c / t))

        # Width: fixed or full-terminal
        if self.full_width:
            w = max(6, _term_cols() - self.margin)
        else:
            w = self.width

        inner = max(2, w - 2)  # reserve [ .. ]
        filled = int(math.floor(inner * pct))
        empty = max(0, inner - filled)

        # Base bar
        bar_chars = [self.fill_char] * filled + [self.empty_char] * empty

        # Overlay percent text *inside* the bar if requested
        if self.show_percent:
            text = f"{int(round(100 * pct)):3d}%"
            start = max(0, (inner - len(text)) // 2)
            for i, ch in enumerate(text):
                if 0 <= start + i < len(bar_chars):
                    bar_chars[start + i] = ch

        return "[" + "".join(bar_chars) + "]"
