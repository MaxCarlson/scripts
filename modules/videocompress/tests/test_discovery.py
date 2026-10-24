"""
Tests for scoped video discovery and filesystem safety.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from videocompress.discovery import discover_video_files
from videocompress.workspace import resolve_workspace


def test_discover_video_files_in_directory(tmp_path: Path):
    media_dir = tmp_path / "media"
    media_dir.mkdir()

    (media_dir / "vid1.mkv").write_bytes(b"dummy mkv content")
    (media_dir / "vid2.mp4").write_bytes(b"dummy mp4 content")
    (media_dir / "ignore.txt").write_text("dummy text")
    (media_dir / "poster.jpg").write_bytes(b"dummy jpg")

    sub = media_dir / "season1"
    sub.mkdir()
    (sub / "ep1.webm").write_bytes(b"dummy webm")

    # Artifact dir to ignore
    ws_dir = media_dir / ".videocompress"
    ws_dir.mkdir()
    (ws_dir / "cached_clip.mp4").write_bytes(b"dummy cache")

    results = discover_video_files(media_dir, workspace_root=ws_dir)
    rel_paths = {item.relative_path.replace("\\", "/") for item in results}

    assert "vid1.mkv" in rel_paths
    assert "vid2.mp4" in rel_paths
    assert "season1/ep1.webm" in rel_paths
    assert "ignore.txt" not in rel_paths
    assert "poster.jpg" not in rel_paths
    assert not any(".videocompress" in p for p in rel_paths)
    assert len(results) == 3


def test_discover_single_video_file(tmp_path: Path):
    single_file = tmp_path / "single.mp4"
    single_file.write_bytes(b"12345")

    results = discover_video_files(single_file)
    assert len(results) == 1
    assert results[0].relative_path == "single.mp4"
    assert results[0].stat_fingerprint.endswith(":5")


def test_workspace_resolution_and_manifest(tmp_path: Path):
    target = tmp_path / "shows"
    target.mkdir()

    ws = resolve_workspace(target)
    assert ws.root.name.startswith("shows_")
    assert ws.inventory_db.name == "inventory.sqlite3"
    assert ws.trials_db.name == "trials.sqlite3"
    assert ws.manifest_file.exists()

    # Verify workspace root is outside target
    assert not ws.root.is_relative_to(target)
