#!/usr/bin/env python3
from __future__ import annotations

import io

from termdash import TermDash
from termdash.seemake import SeemakePrinter


def test_seemake_scrolling_output_and_bar():
    # Capture a plain mirror stream instead of patching stdout
    mirror = io.StringIO()

    td = TermDash(status_line=True, refresh_rate=0.01)

    with td:
        sm = SeemakePrinter(total=4, td=td, with_bar=True, bar_width=16, label="Build", out=mirror)
        sm.step("Scanning dependencies of target myexample", kind="scan")
        sm.step("Building CXX object CMakeFiles/myexample.dir/main.cpp.o", kind="build")

        # Check progress-line stats (without needing to render thread timing)
        assert td.read_stat("seemake:progress", "count") == "2/4"

        sm.step("Linking CXX executable myexample", kind="link")
        sm.step("Built target myexample", kind="success")

    s = mirror.getvalue()
    # Verify CMake-like prefixes appeared
    assert "[ 25%]" in s and "Scanning dependencies" in s
    assert "[ 50%]" in s and "Building CXX object" in s
    assert "[100%]" in s and "Built target" in s
