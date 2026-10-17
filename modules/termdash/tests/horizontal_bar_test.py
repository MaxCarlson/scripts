from __future__ import annotations

from termdash.progress import render_horizontal_bar
from termdash.table import _strip_ansi


def test_horizontal_bar_empty():
    bar = render_horizontal_bar(0.0, width=12, brackets=True)
    assert bar == "[          ]"


def test_horizontal_bar_full():
    bar = render_horizontal_bar(1.0, width=12, brackets=True)
    assert bar == "[██████████]"


def test_horizontal_bar_half():
    bar = render_horizontal_bar(0.5, width=12, brackets=True)
    assert bar == "[█████     ]"


def test_horizontal_bar_percentage():
    bar = render_horizontal_bar(0.75, width=12, brackets=True, show_pct=True)
    assert "75.0%" in bar


def test_horizontal_bar_color():
    bar = render_horizontal_bar(0.5, width=12, color="green")
    assert "\033[32m" in bar
    clean = _strip_ansi(bar)
    assert clean == "[█████     ]"


def test_tiny_bar_widths():
    for width in range(4):
        assert len(render_horizontal_bar(0.5, width=width)) <= width
