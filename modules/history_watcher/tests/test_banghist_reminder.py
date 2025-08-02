# tests/test_banghist_reminder.py
import pytest
from history_watcher.actors.banghist_reminder import (
    watcher,
    suggest_bangbang,
    suggest_bang_dollar,
    suggest_negative_index,
    MAX_HISTORY_BUFFER
)

def test_rules_registered():
    names = [name for name, _ in watcher.rules]
    assert "Use `!!` for exact repeats" in names
    assert "Use `!$` for reusing the last argument" in names
    assert "Use `!-n` for recent repeats" in names

def test_suggest_bangbang_once():
    buf = ["git status"]
    suggested = set()
    msg1 = suggest_bangbang("git status", buf, suggested)
    assert msg1 and "!!" in msg1
    msg2 = suggest_bangbang("git status", buf, suggested)
    assert msg2 is None

def test_suggest_bang_dollar():
    buf = ["echo file.txt"]
    suggested = set()
    msg = suggest_bang_dollar("cat file.txt", buf, suggested)
    assert msg and "!$" in msg

def test_suggest_negative_index_once():
    buf = ["a", "b", "build project"]
    suggested = set()
    # index 2 => "!-3" (3 commands ago)
    msg1 = suggest_negative_index("build project", buf, suggested)
    assert msg1 and "!-3" in msg1
    msg2 = suggest_negative_index("build project", buf, suggested)
    assert msg2 is None
