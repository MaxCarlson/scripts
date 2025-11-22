from __future__ import annotations

import os
from pathlib import Path

import pytest

from file_utils import path_ops


def test_normalize_and_add_no_duplicates(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CLIPBOARD_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("PATH", "A;B")
    sysu_mock = type("S", (), {"is_windows": lambda self: True})
    monkeypatch.setattr(path_ops, "SystemUtils", lambda: sysu_mock())
    parts, backup = path_ops.add_path("process", "a")
    assert len(parts) == 2  # A,B (duplicate ignored)
    assert backup.exists()


def test_move_reorders(monkeypatch):
    monkeypatch.setenv("PATH", "A;B;C")
    sysu_mock = type("S", (), {"is_windows": lambda self: False})
    monkeypatch.setattr(path_ops, "SystemUtils", lambda: sysu_mock())
    # write_posix writes to config; avoid by patching
    monkeypatch.setattr(path_ops, "_write_posix_path", lambda parts, scope: os.environ.__setitem__("PATH", ":".join(parts)))
    parts, _ = path_ops.move_path("process", 3, 1)
    assert parts == ["C", "A", "B"]
