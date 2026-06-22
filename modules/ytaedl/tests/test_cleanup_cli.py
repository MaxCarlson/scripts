"""Tests for ytaedl/cleanup_cli.py — cleanup partial and cleanup index subcommands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ytaedl._partial_utils import (
    PARTIAL_DIR_NAME,
    partial_dir_for,
    write_partial_meta,
)
from ytaedl.cleanup_cli import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_partial(proxy_root: Path, channel: str, url: str) -> Path:
    partial_root = proxy_root / channel / PARTIAL_DIR_NAME
    pdir = partial_dir_for(url, partial_root)
    pdir.mkdir(parents=True, exist_ok=True)
    write_partial_meta(pdir, url=url, file_path=f"stars/{channel}.txt", line_num=1, slot=0)
    (pdir / "video.mp4.part").write_bytes(b"x" * 512)
    return pdir


# ---------------------------------------------------------------------------
# Top-level help
# ---------------------------------------------------------------------------

class TestCleanupHelp:
    def test_no_args_prints_help(self, capsys):
        rc = main([])
        assert rc == 0
        out = capsys.readouterr().out
        assert "partial" in out
        assert "index" in out

    def test_help_flag(self, capsys):
        rc = main(["--help"])
        assert rc == 0

    def test_unknown_operation_returns_2(self, capsys):
        rc = main(["unknown"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "unknown" in err


# ---------------------------------------------------------------------------
# ytaedl cleanup partial
# ---------------------------------------------------------------------------

class TestCleanupPartial:
    def test_dry_run_does_not_delete(self, tmp_path):
        pdir = _make_partial(tmp_path, "chan", "https://example.com/v/1")
        rc = main(["partial", "-P", str(tmp_path), "--dry-run"])
        assert rc == 0
        assert pdir.exists()

    def test_deletes_with_confirm(self, tmp_path, monkeypatch):
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        pdir = _make_partial(tmp_path, "chan", "https://example.com/v/2")
        with patch("builtins.input", return_value="DELETE"):
            rc = main(["partial", "-P", str(tmp_path)])
        assert rc == 0
        assert not pdir.exists()

    def test_cancel_does_not_delete(self, tmp_path, monkeypatch):
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        pdir = _make_partial(tmp_path, "chan", "https://example.com/v/3")
        with patch("builtins.input", return_value="no"):
            rc = main(["partial", "-P", str(tmp_path)])
        assert rc == 0
        assert pdir.exists()

    def test_missing_proxy_root_arg_errors(self, capsys):
        # argparse exits when required -P is missing
        with pytest.raises(SystemExit) as exc_info:
            main(["partial"])
        assert exc_info.value.code != 0

    def test_cleans_archive_when_dir_provided(self, tmp_path, monkeypatch):
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        url = "https://example.com/v/archive"
        _make_partial(tmp_path, "chan", url)
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        af = archive_dir / "yt-chan.txt"
        af.write_text(
            f"downloaded\t1.0\t2026-01-01T00:00:00\t100.0\tvid\t{url}\n",
            encoding="utf-8",
        )
        with patch("builtins.input", return_value="DELETE"):
            rc = main(["partial", "-P", str(tmp_path), "-a", str(archive_dir)])
        assert rc == 0
        assert url not in af.read_text()

    def test_partial_help_shows_options(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["partial", "--help"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "--proxy-root" in out or "-P" in out


# ---------------------------------------------------------------------------
# ytaedl cleanup index
# ---------------------------------------------------------------------------

class TestCleanupIndex:
    def _make_url_files(self, root: Path, stems: list[str]) -> list[Path]:
        root.mkdir(parents=True, exist_ok=True)
        paths = []
        for stem in stems:
            p = root / f"{stem}.txt"
            p.write_text("https://example.com/v/1\nhttps://example.com/v/2\n", encoding="utf-8")
            paths.append(p)
        return paths

    def test_dry_run_does_not_write_index(self, tmp_path):
        stars = tmp_path / "stars"
        self._make_url_files(stars, ["channel_a"])
        idx_path = tmp_path / "domain_index.json"

        rc = main([
            "index",
            "-s", str(stars),
            "-H", str(idx_path),
            "--dry-run",
        ])
        assert rc == 0
        assert not idx_path.exists()

    def test_writes_index_without_dry_run(self, tmp_path):
        stars = tmp_path / "stars"
        self._make_url_files(stars, ["channel_b"])
        idx_path = tmp_path / "domain_index.json"

        rc = main([
            "index",
            "-s", str(stars),
            "-H", str(idx_path),
        ])
        assert rc == 0
        assert idx_path.exists()
        data = json.loads(idx_path.read_text())
        assert "queues" in data

    def test_empty_stars_dir_returns_1(self, tmp_path, capsys):
        stars = tmp_path / "stars"
        aebn = tmp_path / "aebn"
        stars.mkdir()
        aebn.mkdir()
        rc = main(["index", "-s", str(stars), "-d", str(aebn)])
        assert rc == 1
        err = capsys.readouterr().err
        assert "No URL files" in err

    def test_nonexistent_dirs_are_silently_skipped(self, tmp_path):
        rc = main([
            "index",
            "-s", str(tmp_path / "ghost_stars"),
            "-d", str(tmp_path / "ghost_aebn"),
        ])
        assert rc == 1  # no URL files found

    def test_index_help_shows_options(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["index", "--help"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "--stars-dir" in out or "-s" in out

    def test_default_log_dir_used_for_index_path(self, tmp_path):
        stars = tmp_path / "stars"
        self._make_url_files(stars, ["channel_c"])
        log_dir = tmp_path / "logs"

        rc = main([
            "index",
            "-s", str(stars),
            "-g", str(log_dir),
        ])
        assert rc == 0
        assert (log_dir / "domain_index.json").exists()
