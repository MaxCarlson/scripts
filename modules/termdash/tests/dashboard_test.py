#!/usr/bin/env python3
from __future__ import annotations

import io
from typing import Any

from termdash import TermDash
from termdash.components import Line, Stat


def test_termdash_add_line_update_read_reset_and_ordering_test(monkeypatch):
    td = TermDash(enable_separators=True)

    l1 = Line("a", stats=[Stat("x", 1, prefix="X ")])
    l2 = Line("b", stats=[Stat("y", 2, prefix="Y ")])

    td.add_line("a", l1)
    td.add_line("b", l2, at_top=True)  # at_top inserts before

    # order: b then a
    assert td._line_order[0] == "b" and td._line_order[1] == "a"

    # stat R/W
    assert td.read_stat("a", "x") == 1
    td.update_stat("a", "x", 5)
    assert td.read_stat("a", "x") == 5

    # reset to initial value
    td.reset_stat("a", "x")
    assert td.read_stat("a", "x") == 1


def test_termdash_add_separator_enabled_disabled_test():
    td1 = TermDash(enable_separators=False)
    td1.add_separator()  # ignored
    assert not any(n.startswith("sep") for n in td1._line_order)

    td2 = TermDash(enable_separators=True)
    td2.add_separator()
    assert any(n.startswith("sep") for n in td2._line_order)


def test_termdash_sum_and_mean_helpers_test():
    td = TermDash()
    td.add_line("w1", Line("w1", stats=[Stat("mbps", 1.0), Stat("num", 10)]))
    td.add_line("w2", Line("w2", stats=[Stat("mbps", 3.0), Stat("num", 20)]))

    assert td.sum_stats("mbps") == 4.0
    assert td.mean_stats("num") == 15.0


def test_termdash_context_manager_and_log_smoke_test(monkeypatch):
    # stable terminal size + capture stdout so log() doesn't write to real TTY
    monkeypatch.setattr("os.get_terminal_size", lambda: (80, 24))
    fake_out = io.StringIO()
    monkeypatch.setattr("sys.stdout", fake_out, raising=False)

    td = TermDash(status_line=True, refresh_rate=0.01)
    td.add_line("hdr", Line("hdr", stats=[Stat("a", 1, prefix="A ")]))

    # enter/exit shouldn't raise; render thread will start and then stop
    with td:
        td.log("hello", level="info")
        td.update_stat("hdr", "a", 2)

    s = fake_out.getvalue()
    # ensure something was written by log()
    assert "hello" in s
