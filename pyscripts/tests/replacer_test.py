#!/usr/bin/env python3
"""Tests for the replacer utility."""

from __future__ import annotations

import argparse
import io
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import replacer
from replacer import ReplacementRunner, ReplacementStats, run_replacement_mode, run_search_mode


@pytest.fixture(autouse=True)
def reset_console(monkeypatch):
    """Force deterministic console output across tests."""
    stream = io.StringIO()
    test_console = replacer.Console(
        file=stream,
        force_terminal=False,
        color_system=None,
        width=120,
        record=True,
        theme=replacer.THEME,
    )
    monkeypatch.setattr(replacer, "console", test_console)
    yield test_console


def make_args(**overrides):
    defaults = dict(
        pattern="foo",
        replacement="bar",
        path=None,
        write=False,
        ignore_case=False,
        exclude=None,
        regex=False,
        rg_bin="rg",
        verbose=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_run_search_mode_prints_summary(monkeypatch, reset_console):
    summary = replacer.SearchSummary()
    summary.register("file.txt", 1, 2)

    class DummyRunner:
        def __init__(self, args):
            self.args = args

        def stream_colored_output(self):
            return 0

        def gather_summary(self):
            return summary, 0

    monkeypatch.setattr(replacer, "RipgrepRunner", lambda args: DummyRunner(args))
    exit_code = run_search_mode(make_args(replacement=None))
    assert exit_code == 0
    output = reset_console.file.getvalue()
    assert "Search Summary" in output
    assert "Files:" in output
    assert "Matches:" in output


def test_replacement_runner_dry_run_shows_diff(tmp_path, reset_console, monkeypatch):
    target = tmp_path / "sample.txt"
    target.write_text("foo value\nsome foo here\n", encoding="utf-8")
    args = make_args(path=[str(tmp_path)], verbose=True)

    class DummyRunner:
        def __init__(self, _args):
            pass

        def stream_colored_output(self):
            return 0

        def files_with_matches(self):
            return ([target], 0)

    monkeypatch.setattr(replacer, "RipgrepRunner", lambda args: DummyRunner(args))

    status = run_replacement_mode(args)
    assert status == 0
    output = reset_console.export_text()
    assert "- 1: foo value" in output
    assert "+ 1: bar value" in output
    assert "Dry run only" in output
    assert target.read_text(encoding="utf-8").startswith("foo value")


def test_replacement_runner_write_updates_files(tmp_path, reset_console, monkeypatch):
    target = tmp_path / "data.txt"
    target.write_text("alpha foo beta", encoding="utf-8")
    args = make_args(path=[str(tmp_path)], write=True)

    class DummyRunner:
        def __init__(self, _args):
            pass

        def stream_colored_output(self):
            return 0

        def files_with_matches(self):
            return ([target], 0)

    monkeypatch.setattr(replacer, "RipgrepRunner", lambda args: DummyRunner(args))

    status = run_replacement_mode(args)
    assert status == 0
    assert target.read_text(encoding="utf-8") == "alpha bar beta"
    output = reset_console.export_text()
    assert "Changes written to disk" in output


def test_replacement_runner_handles_windows_style_glob(tmp_path, monkeypatch):
    nested = tmp_path / "dir"
    nested.mkdir()
    target = nested / "value.txt"
    target.write_text("foo foo", encoding="utf-8")
    win_style = str(nested / "*.txt").replace("/", "\\")

    args = make_args(path=[win_style])
    runner = ReplacementRunner(args)
    files = list(runner.iter_target_files())
    assert target.resolve() in files


def test_to_native_delegates_when_cross_platform_available(monkeypatch):
    monkeypatch.setattr(replacer, "HAVE_CROSS_PLATFORM", True)
    called = {}

    def fake_native(value):
        called["value"] = value
        return "converted"

    monkeypatch.setattr(replacer, "cp_to_native_path", fake_native)
    assert replacer.to_native("X:\\foo") == "converted"
    assert called["value"] == "X:\\foo"


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific expectation")
def test_windows_specific_path_conversion(tmp_path):
    path_value = str(tmp_path / "folder\\file.txt")
    normalized = replacer.normalize_for_fs(path_value)
    assert "\\" in normalized


@pytest.mark.skipif(os.name == "nt", reason="Posix-specific expectation")
def test_posix_specific_path_conversion(tmp_path):
    path_value = str(tmp_path / "folder\\file.txt")
    normalized = replacer.normalize_for_fs(path_value)
    assert "\\" not in normalized
