#!/usr/bin/env python3
"""
Progress bar helpers for TermDash.

`ProgressBar` renders a fixed-width, in-place safe textual bar and exposes
it as a `Stat` (via `.cell()`), so you can drop it into any `Line`.

Design goals
------------
- Width-stable via `Stat(no_expand=True, display_width=...)`.
- No full-screen wipes; safe to use under TermDash's renderer.
- Bindable to callables so the bar reflects external state without manual `.set()`.

Example
-------
    from termdash import Stat
    from termdash.progress import ProgressBar

    pb = ProgressBar("bar", total=100, width=28, show_percent=True)
    line_stats = {
        "done": Stat("done", 0, prefix="Done: "),
        "bar": pb.cell(),
    }
    # Add the line to a TermDash and call pb.set()/pb.advance() as work progresses.
"""

from __future__ import annotations

from typing import Callable, Optional


from .components import Stat


class ProgressBar:
    """A width-stable textual progress bar that plugs into a TermDash `Line`.

    Parameters
    ----------
    name : str
        The `Stat` key for the bar inside a `Line`.
    total : float | int
        The target total. If 0/None, the bar displays 0%.
    current : float | int, default 0
        Initial progress value.
    width : int, default 30
        Total cell width including brackets.
    charset : str, default "block"
        - "block": uses '█'/'░'
        - "ascii": uses '#'/ '-'
    show_percent : bool, default True
        Overlay centered percent inside the bar while keeping width constant.
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
        self.charset = "ascii" if charset == "ascii" else "block"
        self.show_percent = bool(show_percent)

        self._current_fn: Optional[Callable[[], float]] = None
        self._total_fn: Optional[Callable[[], float]] = None

        self._stat = Stat(
            name=name,
            value=self._render_text(self._current, self._total),
            prefix="",
            format_string="{}",
            unit="",
            color="",
            warn_if_stale_s=0,
            no_expand=True,
            display_width=self.width,
        )

    # Public API -----------------------------------------------------
    def cell(self) -> Stat:
        """Return the underlying `Stat` to drop into a `Line`."""
        return self._stat

    def bind(self, current_fn: Callable[[], float], total_fn: Optional[Callable[[], float]] = None) -> None:
        """Bind to callables (bar refreshes on render)."""
        self._current_fn = current_fn
        self._total_fn = total_fn

    def set_total(self, total: float | int) -> None:
        self._total = max(0.0, float(total or 0))
        self._refresh()

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

    # Internals ------------------------------------------------------
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
        self._stat.value = self._render_text(self._read_current(), self._read_total())

    def _render_text(self, current: float, total: float) -> str:
        t = float(total or 0)
        c = max(0.0, float(current or 0))
        ratio = 0.0 if t <= 0 else max(0.0, min(1.0, c / t))

        fill_char, empty_char = ("#", "-") if self.charset == "ascii" else ("█", "░")

        inner_w = max(1, self.width - 2)  # brackets '[]'
        filled = int(round(ratio * inner_w))
        empty = max(0, inner_w - filled)
        bar_inner = (fill_char * filled) + (empty_char * empty)

        if self.show_percent:
            pct_text = f"{int(round(ratio * 100)):3d}%"
            start = max(0, (len(bar_inner) - len(pct_text)) // 2)
            bar_inner = bar_inner[:start] + pct_text + bar_inner[start + len(pct_text):]

        return f"[{bar_inner}]"
