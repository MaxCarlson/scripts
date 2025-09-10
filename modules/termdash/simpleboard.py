#!/usr/bin/env python3
"""
SimpleBoard: a minimal, modular stats+progress layout builder on top of TermDash.

This is intentionally lightweight:
- You choose rows and drop in `Stat` and `ProgressBar.cell()` items.
- No screen wipe; it relies on TermDash's in-place renderer.
- Single-threaded friendly: you don't need to start the dashboard to mutate stats.

Example
-------
    from termdash import Stat
    from termdash.progress import ProgressBar
    from termdash.simpleboard import SimpleBoard

    board = SimpleBoard(title="Demo")
    # Row 1: two stats
    board.add_row("r1",
        Stat("files_done", 0, prefix="Done: "),
        Stat("files_total", 10, prefix="Total: "),
    )

    # Row 2: a progress bar bound to the first stat
    pb = ProgressBar("bar1", total=10, width=24)
    pb.bind(current_fn=lambda: board.read_stat("r1", "files_done"),
            total_fn=lambda: board.read_stat("r1", "files_total"))
    board.add_row("r2", pb.cell())

    # Optionally run the live dashboard
    # with board.start():
    #     ... do work, call board.update() / pb.advance() ...

Notes
-----
- `add_row` can accept any number of cells; use multiple calls to create multiple rows.
- For testing, you can construct and update without starting the renderer.
"""

from __future__ import annotations

from typing import Any

from .dashboard import TermDash
from .components import Line, Stat

class SimpleBoard:
    """Simple row-based builder for stats and progress bars on TermDash."""
    def __init__(self, *, title: str | None = None, **termdash_kwargs: Any) -> None:
        self.title = title or ""
        # Keep the dashboard idle by default; tests can mutate without starting threads.
        self.td = TermDash(**termdash_kwargs)

        if self.title:
            self.td.add_line("_title", Line("_title", stats={
                "title": Stat("title", self.title, prefix="", format_string="{}", color="1;36", no_expand=True)
            }, style="header"))

    # Row management
    def add_row(self, name: str, *cells: Stat) -> None:
        """Add a row with the given `Stat` cells (including `ProgressBar.cell()`)."""
        if not cells:
            raise ValueError("add_row requires at least one cell (Stat or ProgressBar.cell())")
        stats = {}
        for idx, c in enumerate(cells):
            if not isinstance(c, Stat):
                raise TypeError(f"Row cell {idx} is not a Stat; got {type(c)!r}")
            # Ensure unique keys within the line by using each Stat's name.
            stats[c.name] = c
        self.td.add_line(name, Line(name, stats=stats, style="default"))

    # Convenience wrappers
    def update(self, line: str, stat: str, value: Any) -> None:
        self.td.update_stat(line, stat, value)

    def reset(self, line: str, stat: str, grace_period_s: float = 0) -> None:
        self.td.reset_stat(line, stat, grace_period_s)

    def read_stat(self, line: str, stat: str):
        return self.td.read_stat(line, stat)

    # Lifecycle
    def start(self):
        """Start rendering; returns self so it can be used as a context manager."""
        self.td.start()
        return self

    def stop(self):
        self.td.stop()

    def __enter__(self):
        self.td.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.td.__exit__(exc_type, exc, tb)
