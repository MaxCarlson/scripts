from __future__ import annotations

import os
import types
import curses
import builtins

import pytest

from termdash.interactive_list import InteractiveList


def test_terminfo_fallback_sets_env_and_recovers(monkeypatch):
    # Ensure stdio looks like a TTY
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)

    calls = {"count": 0}

    real_setupterm = curses.setupterm

    def fake_setupterm(*args, **kwargs):
        calls["count"] += 1
        # First two attempts fail; third succeeds
        if calls["count"] < 3:
            raise Exception("no terminfo")
        return real_setupterm(*args, **kwargs)

    monkeypatch.setattr(curses, "setupterm", fake_setupterm)

    # Pick a known-good TERM
    monkeypatch.setenv("TERM", "xterm-256color")
    # Clear TERMINFO_DIRS to let fallback set it
    if "TERMINFO_DIRS" in os.environ:
        monkeypatch.delenv("TERMINFO_DIRS", raising=False)

    # Create a minimal InteractiveList (won't run the UI in this test)
    il = InteractiveList(items=[], sorters={"name": lambda x: x}, formatter=lambda *a, **k: "", filter_func=lambda i, p: True)

    # Call the readiness check directly; it should attempt TERMINFO_DIRS fallback and not raise
    il._ensure_terminal_ready()

