"""Tests for path_manager core utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from path_manager import core


class FakeSystem:
    def __init__(self, windows: bool = True) -> None:
        self._windows = windows

    def is_windows(self) -> bool:
        return self._windows


def test_split_path_string_dedupes_and_strips():
    system = FakeSystem(windows=True)
    messy = '  "C:\\Tools"  ;;  C:\\Tools  ;  C:\\Bin  ;  '
    parts = core.split_path_string(messy, system=system)
    assert parts == ["C:\\Tools", "C:\\Bin"]


def test_build_new_string_remove_contains():
    system = FakeSystem(windows=True)
    base = "C:\\A;C:\\Tools\\Bin;C:\\Foo"
    result = core.build_new_string(base, remove=["contains:tools"], cleanup=True, system=system)
    assert result == "C:\\A;C:\\Foo"


def test_coerce_to_directory_for_exe(tmp_path: Path):
    system = FakeSystem(windows=True)
    exe = tmp_path / "tool.exe"
    exe.write_text("x", encoding="utf-8")
    assert core.coerce_to_directory(str(exe), system=system) == tmp_path


def test_list_executables_in_dir_windows_order(tmp_path: Path):
    system = FakeSystem(windows=True)
    (tmp_path / "tool.exe").write_text("x", encoding="utf-8")
    (tmp_path / "tool.cmd").write_text("x", encoding="utf-8")
    (tmp_path / "other.bat").write_text("x", encoding="utf-8")

    mapping = core.list_executables_in_dir(tmp_path, system=system)
    assert "tool" in mapping
    assert mapping["tool"][0].suffix.lower() in (".exe", ".com", ".bat", ".cmd", ".ps1")


def test_analyze_resolution_changes_detects_swap(tmp_path: Path):
    system = FakeSystem(windows=True)
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "tool.exe").write_text("x", encoding="utf-8")
    (dir_b / "tool.exe").write_text("x", encoding="utf-8")

    before = [str(dir_a), str(dir_b)]
    after = [str(dir_b), str(dir_a)]
    changes = core.analyze_resolution_changes(before, after, system=system)
    assert "tool" in changes
