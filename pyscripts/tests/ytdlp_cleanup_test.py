# file: tests/test_cleanup_part_frag.py
# -*- coding: utf-8 -*-
import os
import time
from pathlib import Path
import shutil
import stat
import tempfile

import pytest

from cleanup_part_frag import (
    classify_part_and_frag,
    derive_base_candidates,
    is_partial_or_frag,
    find_duplicate_full_files,
)


@pytest.fixture()
def temp_tree(tmp_path: Path):
    """
    Layout:
      root/
        A/
          movie.mp4
          movie.mp4.part
          clip.mkv-frag12
        B/
          song.m4a
          song.m4a.part
          stale.mkv-frag9   (mtime = old)
        C/
          dup1.mp4
          sub/dup2_different_name.mp4  (same content as dup1)
          active.tmp.part              (recent mtime)
    """
    root = tmp_path
    (root / "A").mkdir()
    (root / "B").mkdir()
    (root / "C").mkdir()
    (root / "C" / "sub").mkdir(parents=True)

    # Helpers
    def write(p: Path, data: bytes = b"x" * 10):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    # A
    write(root / "A" / "movie.mp4", b"\x00" * 100)
    write(root / "A" / "movie.mp4.part", b"\x00" * 5)
    write(root / "A" / "clip.mkv-frag12", b"\x00" * 5)

    # B
    write(root / "B" / "song.m4a", b"song" * 25)
    write(root / "B" / "song.m4a.part", b"part")
    write(root / "B" / "stale.mkv-frag9", b"oldfrag")
    # make 'stale' old
    old_time = time.time() - 15 * 86400
    os.utime(root / "B" / "stale.mkv-frag9", (old_time, old_time))

    # C duplicates
    payload = b"same-content" * 100
    write(root / "C" / "dup1.mp4", payload)
    write(root / "C" / "sub" / "dup2_different_name.mp4", payload)

    # recent active
    write(root / "C" / "active.tmp.part", b"now")
    recent_time = time.time()  # ensure it's recent
    os.utime(root / "C" / "active.tmp.part", (recent_time, recent_time))

    return root


def test_is_partial_or_frag_detection(tmp_path):
    a = tmp_path / "a.mp4.part"
    b = tmp_path / "b-frag10"
    c = tmp_path / "c.mkv-frag77"
    d = tmp_path / "normal.mp4"
    a.write_text("x")
    b.write_text("x")
    c.write_text("x")
    d.write_text("x")
    assert is_partial_or_frag(a)
    assert is_partial_or_frag(b)
    assert is_partial_or_frag(c)
    assert not is_partial_or_frag(d)


@pytest.mark.parametrize(
    "name,expected_first",
    [
        ("movie.mp4.part", "movie.mp4"),
        ("clip.mkv-frag12", "clip.mkv"),
        ("sample.part-frag22", "sample"),
        ("weird.FRAG9", "weird"),  # generic fallback
    ],
)
def test_derive_base_candidates(name, expected_first):
    cands = derive_base_candidates(name)
    assert cands[0].startswith(expected_first)


def test_classification(temp_tree: Path):
    classified, per_folder = classify_part_and_frag(
        temp_tree, recent_hours=24, old_days=7
    )

    # Completed leftovers: movie.mp4.part (A), song.m4a.part (B)
    leftover_names = {p.name for p in classified.completed_leftovers}
    assert "movie.mp4.part" in leftover_names
    assert "song.m4a.part" in leftover_names

    # Orphans old: stale.mkv-frag9 (B)
    orphan_old_names = {p.name for p in classified.orphans_old}
    assert "stale.mkv-frag9" in orphan_old_names

    # Maybe active: active.tmp.part (C)
    maybe_names = {p.name for p in classified.maybe_active}
    assert "active.tmp.part" in maybe_names

    # clip.mkv-frag12 has no base in A and is not old -> unknown
    unknown_names = {p.name for p in classified.orphans_unknown}
    assert "clip.mkv-frag12" in unknown_names

    # Per-folder counts should sum correctly
    for folder, counts in per_folder.items():
        total = sum(counts.values())
        assert total >= 0  # presence check
    assert sum(v.get("completed_leftovers", 0) for v in per_folder.values()) == 2


def test_duplicates(temp_tree: Path):
    dups = find_duplicate_full_files(temp_tree)
    # exactly one duplicate group with 2 paths (dup1 and dup2_different_name)
    groups = list(dups.values())
    assert len(groups) == 1
    assert len(groups[0]) == 2
