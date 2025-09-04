# Ensures the project root (parent of tests/) is importable
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os
import time
import pytest

from ytdlp_cleanup import (
    classify_part_and_frag,
    derive_base_candidates,
    is_partial_or_frag,
    find_duplicate_full_files,
)

@pytest.fixture()
def temp_tree(tmp_path: Path):
    root = tmp_path
    (root / "A").mkdir()
    (root / "B").mkdir()
    (root / "C" / "sub").mkdir(parents=True)

    def write(p: Path, data: bytes = b"x"*10):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    # Full files + completed leftovers
    write(root / "A" / "movie.mp4", b"\x00"*100)
    write(root / "A" / "movie.mp4.part", b"\x00"*5)

    write(root / "B" / "song.m4a", b"song"*25)
    write(root / "B" / "song.m4a.part", b"part")

    # Orphan old frag (no base present)
    write(root / "B" / "stale.mkv-frag9", b"old")
    old_t = time.time() - 15*86400
    os.utime(root / "B" / "stale.mkv-frag9", (old_t, old_t))

    # Unknown (no base, not old)
    write(root / "A" / "clip.mkv-frag12", b"xx")

    # Active (recent .part)
    write(root / "C" / "active.tmp.part", b"now")
    now = time.time()
    os.utime(root / "C" / "active.tmp.part", (now, now))

    # Duplicates
    payload = b"same-content"*50
    write(root / "C" / "dup1.mp4", payload)
    write(root / "C" / "sub" / "dup2_othername.mp4", payload)

    return root

def test_detection_flags(tmp_path: Path):
    a = tmp_path / "a.mp4.part"
    b = tmp_path / "b-frag10"
    c = tmp_path / "normal.mp4"
    a.write_text("x")
    b.write_text("x")
    c.write_text("x")
    assert is_partial_or_frag(a)
    assert is_partial_or_frag(b)
    assert not is_partial_or_frag(c)

@pytest.mark.parametrize(
    "name,expected_prefix",
    [
        ("movie.mp4.part", "movie.mp4"),
        ("clip.mkv-frag12", "clip.mkv"),
        ("sample.part-frag22", "sample"),
    ],
)
def test_base_candidates(name, expected_prefix):
    cands = derive_base_candidates(name)
    assert cands and cands[0].startswith(expected_prefix)

def test_classification_two_buckets(temp_tree: Path):
    classified, per_folder = classify_part_and_frag(
        temp_tree, recent_hours=24, old_days=7
    )
    safe = {p.name for p in classified.safe_to_delete}
    keep = {p.name for p in classified.keep_for_now}

    # safe_to_delete should include completed leftovers and old orphan
    assert "movie.mp4.part" in safe
    assert "song.m4a.part" in safe
    assert "stale.mkv-frag9" in safe

    # keep_for_now should include recent active and unknown
    assert "active.tmp.part" in keep
    assert "clip.mkv-frag12" in keep

    # per-folder counts have totals
    assert sum(sum(v.values()) for v in per_folder.values()) == len(safe) + len(keep)

def test_duplicates(temp_tree: Path):
    dups = find_duplicate_full_files(temp_tree)
    groups = list(dups.values())
    assert len(groups) == 1
    assert len(groups[0]) == 2
