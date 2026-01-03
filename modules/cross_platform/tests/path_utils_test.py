"""Tests for cross_platform.path_utils."""

from pathlib import Path

import os
import pytest

from cross_platform.path_utils import expand_path, to_posix_path, to_native_path


class DummySystem:
    def __init__(self, is_windows_result: bool):
        self._is_windows_result = is_windows_result

    def is_windows(self) -> bool:
        return self._is_windows_result


def test_expand_path_expands_env_and_home(monkeypatch, tmp_path):
    temp_home = tmp_path / "home"
    temp_home.mkdir()
    monkeypatch.setenv("TEST_VAR", "value")
    monkeypatch.setenv("HOME", str(temp_home))
    monkeypatch.setenv("USERPROFILE", str(temp_home))
    result = expand_path("$TEST_VAR/dir")
    assert result.endswith("value/dir")
    assert expand_path("~/docs").startswith(str(temp_home))


def test_to_posix_path_handles_windows_drive(monkeypatch):
    path = "C:\\Users\\example\\project\\file.txt"
    assert to_posix_path(path) == "C:/Users/example/project/file.txt"


def test_to_posix_path_handles_unc_paths():
    path = r"\\Server\Share\Folder"
    assert to_posix_path(path) == "//Server/Share/Folder"


@pytest.mark.parametrize(
    "is_windows,expected",
    [
        (True, "C:\\Users\\example\\project"),
        (False, "C:/Users/example/project"),
    ],
)
def test_to_native_path_respects_platform(monkeypatch, is_windows, expected):
    dummy = DummySystem(is_windows)
    raw = "C:/Users/example/project"
    assert to_native_path(raw, system=dummy) == expected
