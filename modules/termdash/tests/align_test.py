#!/usr/bin/env python3
from __future__ import annotations

from termdash import TermDash
from termdash.components import Line, Stat


def _pipe_positions(s: str) -> tuple[int, ...]:
    return tuple(i for i, ch in enumerate(s) if ch == "|")


def test_termdash_align_columns_with_noexpand_and_widths_test():
    td = TermDash(align_columns=True, column_sep="|", min_col_pad=1, max_col_width=16)

    # Two lines, different raw lengths; ID and TITLE are no-expand (shouldn't affect column widths)
    l1 = Line(
        "w1",
        stats=[
            Stat("left", "Worker 1", prefix="", no_expand=True, display_width=9),
            Stat("set", "main:agatha_vega", prefix=" Set "),
            Stat("urls", (1, 22), prefix=" URLs ", format_string="{}/{}"),
        ],
    )
    l2 = Line(
        "w2",
        stats=[
            Stat("left", "Worker 2", prefix="", no_expand=True, display_width=9),
            Stat("set", "main:aika_javhd", prefix=" Set "),
            Stat("urls", (10, 13), prefix=" URLs ", format_string="{}/{}"),
        ],
    )

    # Render both; then feed to private aligner (unit-level check)
    s1 = l1.render(120)
    s2 = l2.render(120)

    out = td._align_rendered_lines([s1, s2], cols=120)
    assert len(out) == 2

    # All pipe positions should match across aligned lines
    p1 = _pipe_positions(out[0])
    p2 = _pipe_positions(out[1])
    assert p1 == p2 and len(p1) >= 2

    # Hard clipping should keep widths bounded (no line should exceed cols)
    assert len(out[0]) <= 120 and len(out[1]) <= 120
