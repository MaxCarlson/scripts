#!/usr/bin/env python3
"""
SimpleBoard: a minimal row-based "stats + progress bars" builder atop TermDash.

- You choose rows and drop in `Stat` and `ProgressBar.cell()` items.
- No screen wipe; uses TermDash's in-place renderer.
- Single-thread friendly: works without starting the renderer.
"""

from __future__ import annotations

from typing import Any

from .dashboard import TermDash
from .components import Line, Stat


class SimpleBoard:
    """Simple row-based builder for stats and progress bars on TermDash."""
    def __init__(self, *, title: str | None = None, **termdash_kwargs: Any) -> None:
        self.title = title or ""
        self.td = TermDash(**termdash_kwargs)

        if self.title:
            # IMPORTANT: Line expects an iterable of Stat, not a dict.
            self.td.add_line(
                "_title",
                Line("_title", stats=[Stat("title", self.title, prefix="", format_string="{}", color="1;36", no_expand=True)],
                     style="header"),
            )

    def add_row(self, name: str, *cells: Stat) -> None:
        """Add a row with the given `Stat` cells (including `ProgressBar.cell()`)."""
        if not cells:
            raise ValueError("add_row requires at least one cell")
        stats = list(cells)
        self.td.add_line(name, Line(name, stats=stats, style="default"))

    # Convenience wrappers
    def update(self, line: str, stat: str, value: Any) -> None:
        self.td.update_stat(line, stat, value)

    def reset(self, line: str, stat: str, grace_period_s: float = 0) -> None:
        self.td.reset_stat(line, stat, grace_period_s)

    def read_stat(self, line: str, stat: str):
        return self.td.read_stat(line, stat)

    # Lifecycle helpers
    def start(self):
        self.td.start()
        return self

    def stop(self):
        self.td.stop()

    def __enter__(self):
        self.td.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.td.__exit__(exc_type, exc, tb)
