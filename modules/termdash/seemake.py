#!/usr/bin/env python3
"""
SeemakePrinter: CMake-like scrolling build output for TermDash.

Features
--------
- Left-justified lines with "[ xx%]" prefix and colored action text.
- Optional bottom in-place progress line with percent + bar + count.
- Works with or without a running `TermDash`.
- NEW: optional `out` stream to mirror output in plain text (useful for tests
  and non-TTY environments).

Usage
-----
    from termdash import TermDash
    from termdash.seemake import SeemakePrinter

    td = TermDash(status_line=True)
    with td:
        sm = SeemakePrinter(total=4, td=td, with_bar=True, bar_width=24, label="Build")
        sm.step("Scanning dependencies of target myexample", kind="scan")
        sm.step("Building CXX object CMakeFiles/myexample.dir/main.cpp.o", kind="build")
        sm.step("Linking CXX executable myexample", kind="link")
        sm.step("Built target myexample", kind="success")
"""

from __future__ import annotations

from typing import Optional, TextIO

from .dashboard import TermDash
from .components import Line, Stat
from .progress import ProgressBar


def _color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


_KIND_TO_COLOR = {
    "scan": "1;35",      # bright magenta
    "build": "0;34",     # blue
    "compile": "0;34",
    "link": "0;32",      # green
    "install": "0;36",   # cyan
    "test": "1;33",      # bright yellow
    "success": "1;32",   # bright green
    "warn": "1;33",
    "error": "1;31",
    "info": "0;37",
}


class SeemakePrinter:
    """Emit CMake-like build lines and (optionally) a bottom progress bar."""

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
        if total <= 0:
            raise ValueError("total must be > 0")
        self.total = int(total)
        self.current = 0
        self.td = td
        self.with_bar = bool(with_bar)
        self.label = label
        self.out = out

        self._bar: Optional[ProgressBar] = None
        if self.with_bar and self.td is not None:
            # Bottom progress line: "[ xx%]" + bar + "i/N" + label
            pct = Stat("pct", "[  0%]", prefix="", format_string="{}", no_expand=True, display_width=6)
            count = Stat("count", f"0/{self.total}", prefix="", format_string="{}", no_expand=True, display_width=12)
            lab = Stat("label", label, prefix="", format_string="{}", no_expand=False)

            self._bar = ProgressBar("bar", total=self.total, width=bar_width, show_percent=False)
            line = Line("seemake:progress", stats=[pct, self._bar.cell(), count, lab])
            self.td.add_line("seemake:progress", line)

    # Public API -----------------------------------------------------
    def step(self, message: str, *, kind: str = "info", weight: int = 1) -> None:
        """Advance by `weight` and emit a line."""
        self.current = min(self.total, self.current + max(1, int(weight)))
        pct = int(round(100.0 * self.current / self.total))
        self._emit(message, kind=kind, percent=pct)
        self._update_bar(pct)

    def emit(self, message: str, *, kind: str = "info", percent: Optional[int] = None) -> None:
        """Emit a line without advancing progress (percent optional)."""
        if percent is None:
            percent = int(round(100.0 * self.current / self.total))
        self._emit(message, kind=kind, percent=percent)
        self._update_bar(percent)

    # Internals ------------------------------------------------------
    def _emit(self, message: str, *, kind: str, percent: int) -> None:
        pfx = f"[{percent:3d}%] "
        colored = _color(message, _KIND_TO_COLOR.get(kind, "0;37"))
        line = pfx + colored

        if self.td is not None:
            # Use TermDash's scrolling log
            self.td.log(line, level="info")

        # Always mirror to plain stream if provided
        if self.out is not None:
            try:
                self.out.write(pfx + message + "\n")
            except Exception:
                pass

    def _update_bar(self, percent: int) -> None:
        if not (self.with_bar and self.td is not None):
            return
        try:
            self.td.update_stat("seemake:progress", "pct", f"[{percent:3d}%]")
            self.td.update_stat("seemake:progress", "count", f"{self.current}/{self.total}")
            if self._bar is not None:
                self._bar.set(self.current)
        except Exception:
            # Non-fatal: keep scrolling output usable even if a stat isn't present.
            pass
