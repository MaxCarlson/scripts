from __future__ import annotations

import os
from pathlib import Path

from clipboard_tools import buffers


def test_save_and_load_buffer_round_trip(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CLIPBOARD_STATE_DIR", str(tmp_path))
    text = "hello world\nline2"
    meta = buffers.save_buffer(3, text, set_active=True)
    snap = buffers.load_buffer(3)
    assert snap.text == text
    assert meta["chars"] == len(text)
    assert meta["lines"] == len(text.splitlines())
    assert meta["words"] == len(text.split())


def test_validate_buffer_range():
    assert buffers.validate_buffer_id(None) == 0
    assert buffers.validate_buffer_id(99) == 99
    for bad in (-1, 100):
        try:
            buffers.validate_buffer_id(bad)
        except ValueError:
            pass
        else:
            assert False, "Expected ValueError for out-of-range buffer id"
