"""
CLI tests to catch runtime mismatches (e.g., unexpected DownloaderConfig kwargs).
These ensure `-L/--log-file`, `-C/--save-covers`, and basic run wiring don't crash.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _make_url_file(tmp_path: Path) -> Path:
    f = tmp_path / "urls.txt"
    f.write_text("http://example.com/video/1\n")
    return f


def test_cli_main_runs_without_typeerror(tmp_path: Path, monkeypatch):
    # import inside test to ensure we patch the right symbols
    import ytaedl.cli as cli

    # Prepare inputs
    url_file = _make_url_file(tmp_path)
    out_dir = tmp_path / "out"
    log_file = tmp_path / "run.log"

    # Stub DownloadRunner so it doesn't spawn anything
    class DummyRunner:
        def __init__(self, cfg, ui=None):
            # A very common failure is unexpected kwargs passed to DownloaderConfig.
            # If cli.py passes an unknown kwarg, constructing cfg would raise before this.
            self.cfg = cfg
            self.ui = ui

        def run_from_files(self, url_files, base_out, per_file_subdirs=True):
            # Basic sanity checks
            assert list(url_files) == [url_file]
            assert base_out == out_dir
            assert per_file_subdirs is True

    monkeypatch.setattr(cli, "DownloadRunner", DummyRunner)

    # Run the CLI
    rc = cli.main(
        [
            "-u",
            str(url_file),
            "-o",
            str(out_dir),
            "-j",
            "1",
            "-L",
            str(log_file),
            "-C",
        ]
    )
    assert rc == 0


def test_cli_accepts_url_dir_and_no_keep_covers_crash(tmp_path: Path, monkeypatch):
    import ytaedl.cli as cli

    # Create a directory with .txt files
    url_dir = tmp_path / "batch"
    url_dir.mkdir()
    f1 = url_dir / "list1.txt"
    f1.write_text("http://example.com/a\n")
    out_dir = tmp_path / "out"

    # Track whether we got called
    called = {"ok": False}

    class DummyRunner:
        def __init__(self, cfg, ui=None):
            # CLI used to pass keep_covers -> TypeError. If that regresses, this test will fail before here.
            assert hasattr(cfg, "save_covers")
            called["ok"] = True

        def run_from_files(self, url_files, base_out, per_file_subdirs=True):
            pass

    monkeypatch.setattr(cli, "DownloadRunner", DummyRunner)

    rc = cli.main(["-U", str(url_dir), "-o", str(out_dir), "-K"])
    assert rc == 0
    assert called["ok"] is True
