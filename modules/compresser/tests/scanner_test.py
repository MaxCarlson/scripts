from __future__ import annotations

from pathlib import Path
from compresser.scanner import scan_directory, select_sample, inspect_image_file


def test_scan_directory(sample_images_dir: Path):
    summary, images = scan_directory(sample_images_dir)
    assert summary.total_images == 4
    assert len(images) == 4
    assert "JPEG" in summary.format_counts
    assert "WEBP" in summary.format_counts
    assert "PNG" in summary.format_counts
    assert summary.format_counts["JPEG"] == 2
    assert summary.total_bytes > 0


def test_select_sample(sample_images_dir: Path):
    _, images = scan_directory(sample_images_dir)
    sampled = select_sample(images, 2)
    assert len(sampled) == 2


def test_inspect_single_file(sample_images_dir: Path):
    meta = inspect_image_file(sample_images_dir / "001.jpg", check_grayscale=True)
    assert meta is not None
    assert meta.width == 200
    assert meta.height == 300
    assert meta.format == "JPEG"
    assert not meta.is_tall_for_webp
