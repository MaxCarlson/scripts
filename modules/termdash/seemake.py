#!/usr/bin/env python3
from __future__ import annotations

import sys
from typing import Optional, TextIO

from .components import Line, Stat
from .progress import ProgressBar
from .dashboard import TermDash  # type: ignore


COLORS = {
    "scan": "1;35",      # bright magenta
    "build": "0;34",     # blue
    "compile": "0;34",   # blue
    "link": "0;32",      # green
    "install": "0;36",   # cyan
    "test": "1;33",      # bright yellow
    "success": "1;32",   # bright green
    "warn": "1;33",      # bright yellow
    "error": "1;31",     # bright red
    "info": "0",         # default
}


def _colorize(kind: str, msg: str) -> str:
    code = COLORS.get(kind, "0")
    return f"\033[{code}m{msg}\033[0m"


class SeemakePrinter:
    """
    CMake-like scrolling output with optional live bottom progress row.

    - Always prints a line prefixed with "[ xx%]" to `out` (default sys.stdout).
    - If `td` is provided and `with_bar=True`, creates a bottom row:
        pct | bar | count | label
      The bar is bound to the current step/total and will never "finish" early.
    """

    def __init__(
        self,
        total: int,
        *,
        td: Optional[TermDash] = None,
        with_bar: bool = False,
        bar_width: int = 28,
        label: str = "Build",
        out: Optional[TextIO] = None,
    ) -> None:
        self.total = max(1, int(total))
        self.step_no = 0
        self.td = td
        self.with_bar = bool(with_bar)
        self.bar_width = max(10, int(bar_width))
        self.label = label
        self.out = out or sys.stdout

        self._init_bottom_row()

    def _init_bottom_row(self) -> None:
        if not (self.td and self.with_bar):
            return

        # pct | bar | count | label
        self.s_pct = Stat("pct", "[  0%]", no_expand=True, display_width=6)
        self.s_count = Stat("count", "0/{}".format(self.total), no_expand=True)
        self.s_label = Stat("label", self.label, format_string="{}", no_expand=False)

        self.pb = ProgressBar("bar", total=self.total, current=0,
                              width=self.bar_width, show_percent=False, full_width=False)
        self.pb.bind(current_fn=lambda: self.step_no, total_fn=lambda: self.total)

        self.td.add_line(
            "seemake:progress",
            Line("seemake:progress", stats=[self.s_pct, self.pb.cell(), self.s_count, self.s_label])
        )

    # ---------------- printing ----------------

    def _emit_line(self, message: str, kind: str, percent: Optional[int]) -> None:
        p = self._percent() if percent is None else percent
        prefix = f"[{p:3d}%] "
        colored = _colorize(kind, message)
        print(prefix + colored, file=self.out)

    def _percent(self) -> int:
        return int(round(100.0 * min(1.0, self.step_no / float(self.total))))

    def emit(self, message: str, *, kind: str = "info", percent: Optional[int] = None) -> None:
        self._emit_line(message, kind, percent)

    def step(self, message: str, *, kind: str = "info", weight: int = 1) -> None:
        self.step_no = min(self.total, self.step_no + max(1, int(weight)))
        self._emit_line(message, kind, None)

        if self.td and self.with_bar:
            self.td.update_stat("seemake:progress", "pct", f"[{self._percent():3d}%]")
            self.td.update_stat("seemake:progress", "count", f"{self.step_no}/{self.total}")
            # bar is bound; no explicit update needed
