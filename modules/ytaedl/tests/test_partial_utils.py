"""Tests for _partial_utils.py — partial download directory management."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from ytaedl._partial_utils import (
    PARTIAL_DIR_NAME,
    PARTIAL_SYSTEM_MAJOR,
    PARTIAL_SYSTEM_VERSION,
    CleanupResult,
    CleanupTarget,
    _collect_cleanup_targets,
    _fmt_bytes,
    _is_hash_dir,
    check_and_migrate_proxy_root,
    cleanup_partial_dirs,
    confirm_deletion,
    is_partial_version_compatible,
    partial_dir_for,
    partial_root_for,
    print_deletion_summary,
    read_partial_meta,
    remove_archive_entries_for_urls,
    scan_partial_dirs,
    write_partial_meta,
    write_partial_version,
    read_partial_version,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_partial(proxy_root: Path, channel: str, url: str, extra_files: int = 1) -> Path:
    """Create a _partial/<hash>/ dir with meta.json and optional dummy .part files."""
    channel_dir = proxy_root / channel
    partial_root = channel_dir / PARTIAL_DIR_NAME
    pdir = partial_dir_for(url, partial_root)
    pdir.mkdir(parents=True, exist_ok=True)
    write_partial_meta(pdir, url=url, file_path=f"stars/{channel}.txt", line_num=1, slot=0)
    for i in range(extra_files):
        (pdir / f"video_title.f{i:03d}.mp4.part").write_bytes(b"x" * 1024)
    return pdir


# ---------------------------------------------------------------------------
# partial_dir_for / _is_hash_dir
# ---------------------------------------------------------------------------

class TestPartialDirFor:
    def test_deterministic(self, tmp_path):
        root = tmp_path / "_partial"
        url = "https://example.com/video/12345"
        d1 = partial_dir_for(url, root)
        d2 = partial_dir_for(url, root)
        assert d1 == d2

    def test_different_urls_different_dirs(self, tmp_path):
        root = tmp_path / "_partial"
        d1 = partial_dir_for("https://a.com/1", root)
        d2 = partial_dir_for("https://a.com/2", root)
        assert d1 != d2

    def test_name_is_12_hex_chars(self, tmp_path):
        root = tmp_path / "_partial"
        d = partial_dir_for("https://example.com/video", root)
        assert len(d.name) == 12
        assert all(c in "0123456789abcdef" for c in d.name)

    def test_parent_is_partial_root(self, tmp_path):
        root = tmp_path / "_partial"
        d = partial_dir_for("https://example.com/video", root)
        assert d.parent == root

    def test_partial_root_for(self, tmp_path):
        channel = tmp_path / "my_channel"
        assert partial_root_for(channel) == channel / PARTIAL_DIR_NAME


class TestIsHashDir:
    def test_valid(self):
        assert _is_hash_dir("a1b2c3d4e5f6")

    def test_too_short(self):
        assert not _is_hash_dir("a1b2c3d4e5f")

    def test_too_long(self):
        assert not _is_hash_dir("a1b2c3d4e5f67")

    def test_non_hex(self):
        assert not _is_hash_dir("g1b2c3d4e5f6")

    def test_uppercase_invalid(self):
        assert not _is_hash_dir("A1B2C3D4E5F6")


# ---------------------------------------------------------------------------
# write_partial_meta / read_partial_meta
# ---------------------------------------------------------------------------

class TestPartialMeta:
    def test_roundtrip(self, tmp_path):
        pdir = tmp_path / "a1b2c3d4e5f6"
        pdir.mkdir()
        write_partial_meta(pdir, url="https://ex.com/v", file_path="stars/ex.txt", line_num=7, slot=3)
        meta = read_partial_meta(pdir)
        assert meta is not None
        assert meta["url"] == "https://ex.com/v"
        assert meta["file_path"] == "stars/ex.txt"
        assert meta["line_num"] == 7
        assert meta["worker_slot"] == 3
        assert meta["partial_version"] == PARTIAL_SYSTEM_VERSION
        assert "started_at" in meta

    def test_creates_dir(self, tmp_path):
        pdir = tmp_path / "newdir"
        assert not pdir.exists()
        write_partial_meta(pdir, url="https://ex.com/v", file_path="", line_num=1, slot=0)
        assert pdir.exists()
        assert (pdir / "meta.json").exists()

    def test_read_missing(self, tmp_path):
        assert read_partial_meta(tmp_path / "nonexistent") is None

    def test_read_corrupt(self, tmp_path):
        pdir = tmp_path / "bad"
        pdir.mkdir()
        (pdir / "meta.json").write_text("not json", encoding="utf-8")
        assert read_partial_meta(pdir) is None


# ---------------------------------------------------------------------------
# scan_partial_dirs
# ---------------------------------------------------------------------------

class TestScanPartialDirs:
    def test_finds_partial_with_meta(self, tmp_path):
        url = "https://example.com/video/1"
        _make_partial(tmp_path, "channel_a", url)
        results = scan_partial_dirs(tmp_path)
        urls = [r[0] for r in results]
        assert url in urls

    def test_skips_dir_without_meta(self, tmp_path):
        # Create a hash-shaped dir with no meta.json
        pdir = tmp_path / "channel_a" / PARTIAL_DIR_NAME / "a1b2c3d4e5f6"
        pdir.mkdir(parents=True)
        results = scan_partial_dirs(tmp_path)
        assert results == []

    def test_multiple_channels(self, tmp_path):
        url1 = "https://site1.com/v/1"
        url2 = "https://site2.com/v/2"
        _make_partial(tmp_path, "chan1", url1)
        _make_partial(tmp_path, "chan2", url2)
        results = scan_partial_dirs(tmp_path)
        found_urls = {r[0] for r in results}
        assert url1 in found_urls
        assert url2 in found_urls

    def test_empty_proxy_root(self, tmp_path):
        assert scan_partial_dirs(tmp_path) == []

    def test_nonexistent_root(self, tmp_path):
        assert scan_partial_dirs(tmp_path / "ghost") == []

    def test_returns_path_tuples(self, tmp_path):
        url = "https://example.com/v/3"
        pdir = _make_partial(tmp_path, "ch", url)
        results = scan_partial_dirs(tmp_path)
        assert len(results) == 1
        found_url, found_path = results[0]
        assert found_url == url
        assert found_path == pdir


# ---------------------------------------------------------------------------
# _collect_cleanup_targets
# ---------------------------------------------------------------------------

class TestCollectCleanupTargets:
    def test_collects_sizes(self, tmp_path):
        url = "https://example.com/v/1"
        pdir = _make_partial(tmp_path, "chan", url, extra_files=2)
        targets = _collect_cleanup_targets(tmp_path)
        assert len(targets) == 1
        t = targets[0]
        assert t.channel_dir.name == "chan"
        assert len(t.subdirs) == 1
        assert t.file_count >= 2  # meta.json + 2 .part files
        assert t.total_bytes > 0
        assert url in t.urls

    def test_empty(self, tmp_path):
        assert _collect_cleanup_targets(tmp_path) == []

    def test_multiple_channels(self, tmp_path):
        _make_partial(tmp_path, "a", "https://a.com/1")
        _make_partial(tmp_path, "b", "https://b.com/2")
        targets = _collect_cleanup_targets(tmp_path)
        assert len(targets) == 2
        channel_names = {t.channel_dir.name for t in targets}
        assert channel_names == {"a", "b"}


# ---------------------------------------------------------------------------
# _fmt_bytes
# ---------------------------------------------------------------------------

class TestFmtBytes:
    @pytest.mark.parametrize("n, expected_suffix", [
        (500, "B"),
        (1500, "KiB"),
        (2 * 1024 ** 2, "MiB"),
        (3 * 1024 ** 3, "GiB"),
    ])
    def test_units(self, n, expected_suffix):
        result = _fmt_bytes(n)
        assert result.endswith(expected_suffix)


# ---------------------------------------------------------------------------
# confirm_deletion
# ---------------------------------------------------------------------------

class TestConfirmDeletion:
    def test_accepts_DELETE(self, monkeypatch):
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        with patch("builtins.input", return_value="DELETE"):
            assert confirm_deletion() is True

    def test_rejects_other_input(self, monkeypatch):
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        with patch("builtins.input", return_value="yes"):
            assert confirm_deletion() is False

    def test_rejects_non_tty(self, monkeypatch):
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        assert confirm_deletion() is False

    def test_eof_returns_false(self, monkeypatch):
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        with patch("builtins.input", side_effect=EOFError):
            assert confirm_deletion() is False


# ---------------------------------------------------------------------------
# cleanup_partial_dirs
# ---------------------------------------------------------------------------

class TestCleanupPartialDirs:
    def test_dry_run_deletes_nothing(self, tmp_path):
        url = "https://example.com/v/1"
        pdir = _make_partial(tmp_path, "chan", url)
        result = cleanup_partial_dirs(tmp_path, dry_run=True, require_confirm=False)
        assert result.dry_run is True
        assert result.deleted_dirs == 0
        assert pdir.exists()

    def test_deletes_without_confirm(self, tmp_path):
        url = "https://example.com/v/1"
        pdir = _make_partial(tmp_path, "chan", url, extra_files=1)
        result = cleanup_partial_dirs(tmp_path, dry_run=False, require_confirm=False)
        assert result.deleted_dirs == 1
        assert result.deleted_files >= 1
        assert result.freed_bytes > 0
        assert not pdir.exists()

    def test_confirm_required_accepted(self, tmp_path, monkeypatch):
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        url = "https://example.com/v/2"
        _make_partial(tmp_path, "chan", url)
        with patch("builtins.input", return_value="DELETE"):
            result = cleanup_partial_dirs(tmp_path, dry_run=False, require_confirm=True)
        assert result.deleted_dirs == 1

    def test_confirm_required_cancelled(self, tmp_path, monkeypatch):
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        url = "https://example.com/v/3"
        pdir = _make_partial(tmp_path, "chan", url)
        with patch("builtins.input", return_value="no"):
            result = cleanup_partial_dirs(tmp_path, dry_run=False, require_confirm=True)
        assert result.deleted_dirs == 0
        assert pdir.exists()

    def test_empty_root_is_noop(self, tmp_path):
        result = cleanup_partial_dirs(tmp_path, require_confirm=False)
        assert result.deleted_dirs == 0

    def test_does_not_delete_mp4_files(self, tmp_path):
        # Finished MP4 next to _partial/ must never be touched
        channel = tmp_path / "chan"
        channel.mkdir()
        finished_mp4 = channel / "finished_video.mp4"
        finished_mp4.write_bytes(b"mp4data")
        _make_partial(tmp_path, "chan", "https://ex.com/v/1")
        cleanup_partial_dirs(tmp_path, require_confirm=False)
        assert finished_mp4.exists(), "Finished MP4 was incorrectly deleted"

    def test_removes_archive_entries(self, tmp_path):
        url = "https://example.com/v/5"
        _make_partial(tmp_path, "chan", url)
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        archive_file = archive_dir / "yt-chan.txt"
        archive_file.write_text(
            f"downloaded\t1.0\t2026-01-01T00:00:00\t100.0\tvid123\t{url}\n"
            "downloaded\t1.0\t2026-01-01T00:00:00\t100.0\tother\thttps://other.com/v\n",
            encoding="utf-8",
        )
        result = cleanup_partial_dirs(
            tmp_path, archive_dir=archive_dir, require_confirm=False
        )
        assert result.archive_entries_removed == 1
        remaining = archive_file.read_text(encoding="utf-8")
        assert url not in remaining
        assert "https://other.com/v" in remaining


# ---------------------------------------------------------------------------
# remove_archive_entries_for_urls
# ---------------------------------------------------------------------------

class TestRemoveArchiveEntries:
    def test_removes_matching_lines(self, tmp_path):
        url = "https://example.com/v/99"
        af = tmp_path / "arch.txt"
        af.write_text(
            f"downloaded\t1.0\t...\t100.0\tvid\t{url}\n"
            "downloaded\t1.0\t...\t100.0\tother\thttps://keep.com/v\n",
            encoding="utf-8",
        )
        removed = remove_archive_entries_for_urls(tmp_path, [url])
        assert removed == 1
        assert url not in af.read_text()
        assert "https://keep.com/v" in af.read_text()

    def test_empty_url_list(self, tmp_path):
        af = tmp_path / "arch.txt"
        af.write_text("downloaded\t1.0\t...\thttps://ex.com/v\n", encoding="utf-8")
        assert remove_archive_entries_for_urls(tmp_path, []) == 0

    def test_missing_archive_dir(self, tmp_path):
        assert remove_archive_entries_for_urls(tmp_path / "ghost", ["https://ex.com"]) == 0


# ---------------------------------------------------------------------------
# Version management
# ---------------------------------------------------------------------------

class TestVersionManagement:
    def test_write_and_read_version(self, tmp_path):
        proot = tmp_path / "_partial"
        write_partial_version(proot)
        stored = read_partial_version(proot)
        assert stored == PARTIAL_SYSTEM_VERSION

    def test_read_missing_version(self, tmp_path):
        assert read_partial_version(tmp_path / "ghost") is None

    def test_compatible_same_major(self, tmp_path):
        proot = tmp_path / "_partial"
        write_partial_version(proot)
        ok, ver = is_partial_version_compatible(proot)
        assert ok is True
        assert ver == PARTIAL_SYSTEM_VERSION

    def test_incompatible_different_major(self, tmp_path):
        proot = tmp_path / "_partial"
        proot.mkdir(parents=True)
        (proot / ".version").write_text(
            json.dumps({"partial_version": "1.0.0", "created_at": time.time()}),
            encoding="utf-8",
        )
        ok, ver = is_partial_version_compatible(proot)
        assert ok is False
        assert ver == "1.0.0"

    def test_missing_version_is_compatible(self, tmp_path):
        proot = tmp_path / "_partial"
        ok, ver = is_partial_version_compatible(proot)
        assert ok is True
        assert ver is None

    def test_migration_aborted_when_declined(self, tmp_path, monkeypatch):
        # Create a channel with an old-version _partial/ dir that has actual content
        url = "https://example.com/v/old"
        pdir = _make_partial(tmp_path, "chan", url)
        partial_root = pdir.parent  # _partial/ dir (pdir is _partial/<hash>/)
        (partial_root / ".version").write_text(
            json.dumps({"partial_version": "1.0.0"}), encoding="utf-8"
        )
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        with patch("builtins.input", return_value="no"):
            result = check_and_migrate_proxy_root(tmp_path)
        assert result is False

    def test_migration_succeeds_when_confirmed(self, tmp_path, monkeypatch):
        url = "https://example.com/v/migrate"
        pdir = _make_partial(tmp_path, "chan", url)
        partial_root = pdir.parent  # _partial/ dir
        (partial_root / ".version").write_text(
            json.dumps({"partial_version": "1.0.0"}), encoding="utf-8"
        )
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        with patch("builtins.input", return_value="DELETE"):
            result = check_and_migrate_proxy_root(tmp_path)
        assert result is True
        assert not pdir.exists()

    def test_no_mismatch_returns_true(self, tmp_path):
        channel = tmp_path / "chan"
        proot = channel / PARTIAL_DIR_NAME
        write_partial_version(proot)
        assert check_and_migrate_proxy_root(tmp_path) is True
