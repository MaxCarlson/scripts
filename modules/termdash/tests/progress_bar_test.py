#!/usr/bin/env python3
from __future__ import annotations

import re

from termdash.progress import ProgressBar

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
NOEXPAND_RE = re.compile("[\x1e\x1f]")  # RS/US markers
WIDTH_HINT_RE = re.compile(r"\[W(\d+)\]")

def strip_controls(s: str) -> str:
    s = ANSI_RE.sub("", s)
    s = NOEXPAND_RE.sub("", s)
    s = WIDTH_HINT_RE.sub("", s)
    return s

def test_progress_bar_width_and_percent():
    pb = ProgressBar("p", total=200, current=100, width=20, charset="ascii", show_percent=True)
    cell = pb.cell()
    text = cell.render()  # render without logger
    plain = strip_controls(text)
    assert len(plain) == 20
    assert "[" in plain and "]" in plain
    # overlay has a percent roughly centered
    assert "%" in plain

    # advance and verify internal percent helper
    pb.advance(50)
    pct = pb.percent()
    assert 75.0 - 0.01 <= pct <= 75.0 + 0.01

def test_progress_bar_bindings():
    state = {"done": 0, "total": 10}
    pb = ProgressBar("p", total=10, width=16)
    pb.bind(current_fn=lambda: state["done"], total_fn=lambda: state["total"])

    # Before change
    assert int(round(pb.percent())) == 0
    # after change
    state["done"] = 5
    # re-render to refresh (Stat renders on use)
    _ = pb.cell().render()
    assert 49 <= int(round(pb.percent())) <= 51
