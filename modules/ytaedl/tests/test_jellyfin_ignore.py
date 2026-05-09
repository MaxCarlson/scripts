"""Tests for Jellyfin .ignore file creation in _partial_utils.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from ytaedl._partial_utils import (
    JELLYFIN_IGNORE_FILENAME,
    ensure_jellyfin_ignore,
)


class TestEnsureJellyfinIgnore:
    def test_creates_ignore_file(self, tmp_path):
        d = tmp_path / "subdir"
        d.mkdir()
        ensure_jellyfin_ignore(d)
        assert (d / JELLYFIN_IGNORE_FILENAME).exists()

    def test_ignore_file_is_empty(self, tmp_path):
        d = tmp_path / "subdir"
        d.mkdir()
        ensure_jellyfin_ignore(d)
        assert (d / JELLYFIN_IGNORE_FILENAME).read_text() == ""

    def test_idempotent(self, tmp_path):
        d = tmp_path / "subdir"
        d.mkdir()
        ensure_jellyfin_ignore(d)
        ensure_jellyfin_ignore(d)  # second call — no error, no overwrite
        assert (d / JELLYFIN_IGNORE_FILENAME).exists()

    def test_does_not_overwrite_existing_content(self, tmp_path):
        d = tmp_path / "subdir"
        d.mkdir()
        ignore = d / JELLYFIN_IGNORE_FILENAME
        ignore.write_text("custom content", encoding="utf-8")
        ensure_jellyfin_ignore(d)
        assert ignore.read_text() == "custom content"

    def test_filename_constant(self):
        assert JELLYFIN_IGNORE_FILENAME == ".ignore"


class TestIgnoreScopeRules:
    """Verify .ignore is placed at the right directory depth."""

    def test_ignore_in_partial_subdir_not_channel_root(self, tmp_path):
        # Simulate: tmp_path = download_out_dir (channel folder)
        #           tmp_path/_partial/ = partial_root  ← .ignore goes here
        channel_dir = tmp_path / "upperfloor2"
        channel_dir.mkdir()
        partial_root = channel_dir / "_partial"
        partial_root.mkdir()

        # .ignore should be placed IN partial_root
        ensure_jellyfin_ignore(partial_root)
        assert (partial_root / JELLYFIN_IGNORE_FILENAME).exists()

        # .ignore should NOT exist in the channel root
        assert not (channel_dir / JELLYFIN_IGNORE_FILENAME).exists()

    def test_deeper_subdir_gets_no_ignore_automatically(self, tmp_path):
        channel_dir = tmp_path / "chan"
        channel_dir.mkdir()
        partial_root = channel_dir / "_partial"
        partial_root.mkdir()
        hash_dir = partial_root / "a1b2c3d4e5f6"
        hash_dir.mkdir()

        # Only call ensure_jellyfin_ignore for partial_root (per the plan rule)
        ensure_jellyfin_ignore(partial_root)

        # partial_root has .ignore
        assert (partial_root / JELLYFIN_IGNORE_FILENAME).exists()
        # hash_dir does NOT (we don't call it there)
        assert not (hash_dir / JELLYFIN_IGNORE_FILENAME).exists()
