from __future__ import annotations

from pathlib import Path
from PIL import Image
from compresser.engine import CompressionEngine, resolve_output_format, validate_image_file
from compresser.models import CompressionStrategy, ImageMetadata
from compresser.scanner import scan_directory


def test_resolve_output_format():
    normal_meta = ImageMetadata(Path("001.jpg"), "JPEG", 1000, 1500, 50000)
    tall_meta = ImageMetadata(Path("001.jpg"), "JPEG", 1000, 20000, 50000)

    strat_auto = CompressionStrategy(name="auto", format="auto")
    assert resolve_output_format(normal_meta, strat_auto) == "webp"
    # Tall image falls back to jpeg
    assert resolve_output_format(tall_meta, strat_auto) == "jpeg"


def test_engine_dry_run(sample_images_dir: Path):
    _, images = scan_directory(sample_images_dir)
    engine = CompressionEngine()
    strat = CompressionStrategy(name="test-dry", format="webp", mode="perceptual", perceptual_target=0.985)

    batch_res = engine.compress_batch(images, strat, write_mode=False)
    assert batch_res.dry_run is True
    assert batch_res.total_images == 4
    assert batch_res.applied_count == 0

    # Ensure no files were altered or added
    files = list(sample_images_dir.glob("*"))
    assert len(files) == 6  # 4 images + 2 sidecars


def test_engine_write_mode(tmp_path: Path):
    img_dir = tmp_path / "write_test"
    img_dir.mkdir()
    im = Image.new("RGB", (200, 200), color=(100, 150, 200))
    src = img_dir / "001.jpg"
    im.save(src, format="JPEG", quality=90)

    _, images = scan_directory(img_dir)
    engine = CompressionEngine()

    # Refused without explicit allow_lossy
    strat_no_lossy = CompressionStrategy(name="test-write", format="webp", mode="lossy", quality=75, allow_lossy=False)
    batch_res = engine.compress_batch(images, strat_no_lossy, write_mode=True)
    assert batch_res.applied_count == 0
    assert batch_res.skipped_count == 1
    assert src.exists()

    # Allowed with explicit allow_lossy
    strat_allowed = CompressionStrategy(name="test-write", format="webp", mode="lossy", quality=75, allow_lossy=True)
    batch_res = engine.compress_batch(images, strat_allowed, write_mode=True)
    assert batch_res.dry_run is False
    assert batch_res.applied_count == 1

    # Check that original 001.jpg was cleanly replaced by 001.webp
    assert not src.exists()
    dst = img_dir / "001.webp"
    assert dst.exists()
    assert validate_image_file(dst)


def test_engine_crash_recovery(tmp_path: Path):
    from compresser.engine import recover_interrupted_transactions, JOURNAL_FILENAME
    import json

    img_dir = tmp_path / "recovery_test"
    img_dir.mkdir()

    # Scenario: Program crashed after writing and swapping 001.webp, before 001.jpg was unlinked
    im = Image.new("RGB", (100, 100), color=(50, 50, 50))
    orig = img_dir / "001.jpg"
    orig.write_bytes(b"original-jpeg-data")
    dest = img_dir / "001.webp"
    im.save(dest, format="WEBP")

    journal_data = {
        "version": 1,
        "pending_operations": [
            {
                "original_path": str(orig.resolve()),
                "output_path": str(dest.resolve()),
                "temp_path": str((img_dir / "001.webp.tmp").resolve()),
                "state": "prepared",
            }
        ],
    }
    (img_dir / JOURNAL_FILENAME).write_text(json.dumps(journal_data), encoding="utf-8")

    # Both files exist initially
    assert orig.exists()
    assert dest.exists()

    # Legacy records do not prove ownership. Never delete based on decodability.
    import pytest

    with pytest.raises(RuntimeError, match="Legacy"):
        recover_interrupted_transactions(img_dir, apply=True)
    assert orig.exists()
    assert dest.exists()
    assert (img_dir / JOURNAL_FILENAME).exists()
