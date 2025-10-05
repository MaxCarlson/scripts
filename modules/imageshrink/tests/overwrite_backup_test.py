#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

from PIL import Image


def _make_test_image(folder: Path, name: str = "test.jpg") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    img_path = folder / name
    Image.new("RGB", (200, 200), (150, 100, 50)).save(img_path, "JPEG", quality=95)
    return img_path


def test_cli_overwrite(tmp_path: Path):
    """Verify that --overwrite modifies the original file."""
    leaf = tmp_path / "manga" / "leaf_overwrite"
    img_path = _make_test_image(leaf)
    original_size = img_path.stat().st_size

    cmd = [
        sys.executable, "-m", "imgshrink", str(tmp_path / "manga"),
        "--overwrite",
        # Use a small target ratio to ensure file is modified
        "--target-ratio", "0.5",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"CLI failed: {proc.stderr}"

    # Check that the original file was modified and is smaller
    new_size = img_path.stat().st_size
    assert new_size < original_size
    # Check that no _compressed directory was created
    assert not (leaf / "_compressed").exists()


def test_cli_overwrite_with_backup(tmp_path: Path):
    """Verify that --overwrite --backup creates a .orig file."""
    leaf = tmp_path / "manga" / "leaf_backup"
    img_path = _make_test_image(leaf)
    original_size = img_path.stat().st_size
    backup_path = img_path.with_suffix(img_path.suffix + ".orig")

    cmd = [
        sys.executable, "-m", "imgshrink", str(tmp_path / "manga"),
        "--overwrite",
        "--backup",
        "--target-ratio", "0.5",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"CLI failed: {proc.stderr}"

    # Check that the backup file exists and has the original size
    assert backup_path.exists()
    assert backup_path.stat().st_size == original_size

    # Check that the original file was modified
    new_size = img_path.stat().st_size
    assert new_size < original_size
