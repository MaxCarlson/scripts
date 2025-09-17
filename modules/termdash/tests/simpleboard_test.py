#!/usr/bin/env python3
from __future__ import annotations

from termdash.simpleboard import SimpleBoard
from termdash.progress import ProgressBar
from termdash import Stat

def test_simpleboard_add_and_update():
    b = SimpleBoard(title="T")
    # row with two stats
    b.add_row("r1",
        Stat("done", 0, prefix="Done: "),
        Stat("total", 10, prefix="Total: "),
    )
    # bar bound to stat values
    pb = ProgressBar("bar", total=10, width=18)
    pb.bind(current_fn=lambda: b.read_stat("r1", "done"), total_fn=lambda: b.read_stat("r1", "total"))
    b.add_row("r2", pb.cell())

    # mutate and read back
    b.update("r1", "done", 4)
    assert b.read_stat("r1", "done") == 4

    # render the bar cell and ensure it's width-stable
    rendered = pb.cell().render()
    # markers are present (width hint + NOEXPAND markers)
    assert "[W18]" in rendered
    assert "\x1e" in rendered and "\x1f" in rendered  # NOEXPAND markers
