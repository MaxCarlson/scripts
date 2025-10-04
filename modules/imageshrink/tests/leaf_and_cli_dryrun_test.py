#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

from PIL import Image

from imgshrink.analysis import find_leaf_image_dirs


def _mkimg(p: Path, name: str, size=(1024, 1536)):
    p.mkdir(parents=True, exist_ok=True)
    (p / name).write_bytes(b"")  # placeholder; replaced below


def test_find_leaf_dirs(tmp_path: Path):
    # Structure:
    # manga/leaf1 (2 imgs), manga/parent/leaf2 (1 img), manga/nonleaf/sub (1 img)
    leaf1 = tmp_path / "manga" / "leaf1"
    leaf1.mkdir(parents=True)
    (leaf1 / "p1.jpg").write_bytes(b"foo")
    (leaf1 / "p2.png").write_bytes(b"bar")

    parent = tmp_path / "manga" / "parent"
    leaf2 = parent / "leaf2"
    leaf2.mkdir(parents=True)
    (leaf2 / "x.jpg").write_bytes(b"baz")

    nonleaf = tmp_path / "manga" / "nonleaf"
    (nonleaf / "sub").mkdir(parents=True)
    (nonleaf / "sub" / "y.jpg").write_bytes(b"qux")

    leaves = find_leaf_image_dirs(tmp_path / "manga")
    # nonleaf should not be considered a leaf since it has images in a subdir
    assert leaf1 in leaves
    assert leaf2 in leaves
    assert nonleaf not in leaves


def test_cli_dry_run_smoke(tmp_path: Path):
    # make a simple leaf folder with real images
    leaf = tmp_path / "manga" / "leaf"
    leaf.mkdir(parents=True, exist_ok=True)
    for i in range(2):
        Image.new("RGB", (1600 + 200*i, 2200), (100+i, 100, 100)).save(leaf / f"p{i}.jpg", "JPEG", quality=88)

    cmd = [
        sys.executable, "-m", "imgshrink", str(tmp_path / "manga"),
        "-t", "1", "-n", "-S", str(tmp_path / "summary.json")
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    # Allow 0 (success) or None (some environments don't propagate returncode)
    assert proc.returncode == 0 or proc.returncode is None

    # Summary file should exist
    assert (tmp_path / "summary.json").exists()