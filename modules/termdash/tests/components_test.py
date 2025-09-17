#!/usr/bin/env python3
from __future__ import annotations

from termdash.components import Stat, Line


def test_termdash_stat_basic_and_tuple_rendering_test():
    s = Stat("urls", (3, 10), prefix="URLs ", format_string="{}/{}", unit="")
    txt = s.render()
    assert "URLs " in txt and "3/10" in txt

    s = Stat("speed", 12.3456, prefix="Spd ", format_string="{:.1f}")
    out = s.render()
    assert "Spd " in out and "12.3" in out

    # None falls back to last rendered text placeholder
    s = Stat("eta", None, prefix="ETA ")
    out = s.render()
    assert "ETA " in out and "--" in out


def test_termdash_stat_format_errors_and_color_provider_test():
    # Bad format triggers FMT_ERR but does not raise
    s = Stat("oops", 123, prefix="", format_string="{:q}")
    out = s.render()
    assert "FMT_ERR" in out

    # Dynamic color provider callable
    s = Stat("dyn", 5, prefix="X ", color=lambda v: "0;32" if v == 5 else "0;31")
    out = s.render()
    assert "\x1b[" in out  # ANSI applied


def test_termdash_stat_no_expand_markers_present_test():
    s = Stat("id", "42", prefix="ID ", no_expand=True, display_width=8)
    out = s.render()
    # No-expand markers (0x1E .. 0x1F) must wrap the text (aligner uses them)
    assert "\x1e" in out and "\x1f" in out


def test_termdash_line_styles_test():
    # Default line joins stats with " | "
    l_default = Line("L", stats=[Stat("a", 1, prefix="A "), Stat("b", 2, prefix="B ")])
    s_default = l_default.render(80)
    assert "A " in s_default and "B " in s_default and " | " in s_default

    # Header line applies bright/cyan
    l_header = Line("H", stats=[Stat("a", 1, prefix="A ")], style="header")
    s_header = l_header.render(80)
    assert "\x1b[1;36m" in s_header

    # Separator fills exactly requested width
    l_sep = Line("S", style="separator", sep_pattern="─")
    s_sep = l_sep.render(50)
    assert len(s_sep) == 50 and all(ch == "─" for ch in s_sep)
