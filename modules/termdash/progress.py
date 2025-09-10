#!/usr/bin/env python3
"""
Progress bar helpers for TermDash.

This module provides a `ProgressBar` class that renders a fixed-width,
in-place safe progress bar string and exposes it as a TermDash `Stat`
so you can drop it into any `Line`.

Design goals:
- No reliance on clearing the whole screen; just a single-cell string.
- Width-stable via the same NOEXPAND markers TermDash already understands.
- Easy to bind to other stats (via callables) or update manually.

Typical usage
-------------
    from termdash import TermDash, Line, Stat
    from termdash.progress import ProgressBar

    pb = ProgressBar(name="dl_bar", total=100, width=30)
    line = Line("downloads", stats={
        "done": Stat("done", 0, prefix="Done: "),
        "total": Stat("total", 100, prefix="Total: "),
        "bar": pb.cell(),  # drop the stat cell into the line
    })

    td = TermDash()
    td.add_line("downloads", line)
    # td.start()/stop() or use as a context manager elsewhere

    # Update in your loop:
    for i in range(101):
        pb.set(i)      # updates the underlying Stat value with a new bar
        td.update_stat("downloads", "done", i)

You can also *bind* the bar to callables so it refreshes itself
whenever it renders (useful when multiple places mutate state):

    pb.bind(current_fn=lambda: state.files_done, total_fn=lambda: state.files_total)

NOTE: keep widths modest for narrow terminals. The bar string includes the
brackets `[]` and the internal fill area; `width` is the total cell width.
"""

from __future__ import annotations

import math
from typing import Callable, Optional

# Reuse Stat and the no-expand markers used by the TermDash aligner.
from .components import Stat, NOEXPAND_L, NOEXPAND_R

# ANSI reset (we don't color segments inside the bar by default)
RESET = "\033[0m"

class ProgressBar:
    """A width-stable textual progress bar that plugs into a TermDash `Line`.

    Parameters
    ----------
    name : str
        The stat key used within a `Line`.
    total : float | int
        The target total. If 0 or None, the bar will show 0%.
    current : float | int, default 0
        Initial progress value.
    width : int, default 30
        Total cell width including brackets. Must be >= 6 to fit a useful bar.
    charset : str, default "block"
        - "block": uses unicode '█' for fill, '░' for empty.
        - "ascii": uses '#' for fill, '-' for empty.
    show_percent : bool, default True
        When True, overlays a centered percent string inside the bar.
        (keeps the overall width constant).
    """

    def __init__(
        self,
        name: str,
        total: float | int,
        current: float | int = 0,
        *,
        width: int = 30,
        charset: str = "block",
        show_percent: bool = True,
    ) -> None:
        if width < 6:
            raise ValueError("ProgressBar width must be >= 6")
        self.name = name
        self._total = float(total or 0)
        self._current = max(0.0, float(current or 0))
        self.width = int(width)
        self.charset = charset
        self.show_percent = bool(show_percent)

        self._current_fn: Optional[Callable[[], float]] = None
        self._total_fn: Optional[Callable[[], float]] = None

        # The underlying Stat that will be added to a Line.
        # We mark it no_expand with a display_width hint so TermDash aligns it as a fixed cell.
        self._stat = Stat(
            name=name,
            value=self._render_text(self._current, self._total),
            prefix="",
            format_string="{}",
            unit="",
            color="",               # let the Line color, or keep default
            warn_if_stale_s=0,
            no_expand=True,
            display_width=self.width,
        )

    # ----------------
    # Public API
    # ----------------
    def cell(self) -> Stat:
        """Return the underlying `Stat` to drop into a TermDash `Line`."""
        return self._stat

    def bind(self, current_fn: Callable[[], float], total_fn: Optional[Callable[[], float]] = None) -> None:
        """Bind the bar to callables; values will be read at render time."""
        self._current_fn = current_fn
        self._total_fn = total_fn

    def set_total(self, total: float | int) -> None:
        self._total = max(0.0, float(total or 0))

    def set(self, current: float | int) -> None:
        self._current = max(0.0, float(current or 0))
        self._refresh()

    def advance(self, delta: float | int = 1) -> None:
        self._current = max(0.0, float(self._current + (delta or 0)))
        self._refresh()

    def percent(self) -> float:
        t = self._read_total()
        if t <= 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * (self._read_current() / t)))

    # ----------------
    # Internals
    # ----------------
    def _read_current(self) -> float:
        if self._current_fn is not None:
            try:
                return max(0.0, float(self._current_fn() or 0))
            except Exception:
                return max(0.0, float(self._current))
        return self._current

    def _read_total(self) -> float:
        if self._total_fn is not None:
            try:
                return max(0.0, float(self._total_fn() or 0))
            except Exception:
                return max(0.0, float(self._total))
        return self._total

    def _refresh(self) -> None:
        # Recompute bar text and set it as the Stat's value (render() will embed no-expand markers)
        txt = self._render_text(self._read_current(), self._read_total())
        self._stat.value = txt  # Stat will format with "{}" and wrap in NOEXPAND markers

    def _render_text(self, current: float, total: float) -> str:
        # clamp and compute ratio
        t = float(total or 0)
        c = max(0.0, float(current or 0))
        ratio = 0.0 if t <= 0 else max(0.0, min(1.0, c / t))

        # characters
        if self.charset == "ascii":
            fill_char, empty_char = "#", "-"
        else:
            fill_char, empty_char = "█", "░"

        # we include brackets '[]' in the width
        inner_w = max(1, self.width - 2)
        filled = int(round(ratio * inner_w))
        empty = max(0, inner_w - filled)

        bar_inner = (fill_char * filled) + (empty_char * empty)

        if self.show_percent:
            pct_text = f"{int(round(ratio * 100)):3d}%"
            # Overlay centered into the bar_inner without changing length
            start = max(0, (len(bar_inner) - len(pct_text)) // 2)
            bar_inner = (
                bar_inner[:start] +
                pct_text +
                bar_inner[start + len(pct_text):]
            )

        bar = f"[{bar_inner}]"  # total length == self.width

        # To keep column alignment stable in TermDash, apply the NOEXPAND markers
        # with a width hint for the aligner to read.
        return f"{NOEXPAND_L}[W{self.width}]{bar}{NOEXPAND_R}"
