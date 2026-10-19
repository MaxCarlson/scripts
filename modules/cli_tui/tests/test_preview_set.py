from __future__ import annotations

import json
from pathlib import Path

from cli_tui.preview_set import (
    PreviewItem,
    PreviewSet,
    PreviewVariant,
    scan_preview_directory,
)


def test_preview_set_navigation():
    variant1 = PreviewVariant(
        recipe="WebP q85",
        path=Path("sample_01.webp"),
        size_bytes=1000,
        original_size_bytes=2000,
        format="webp",
        quality=85,
    )
    variant2 = PreviewVariant(
        recipe="WebP q70",
        path=Path("sample_01_q70.webp"),
        size_bytes=800,
        original_size_bytes=2000,
        format="webp",
        quality=70,
    )
    item1 = PreviewItem(
        source_path=Path("sample_01.png"),
        size_bytes=2000,
        variants=[variant1, variant2],
    )

    item2 = PreviewItem(
        source_path=Path("sample_02.png"),
        size_bytes=3000,
        variants=[variant1],
    )

    preview_set = PreviewSet(items=[item1, item2])
    assert len(preview_set.items) == 2
    assert preview_set.current_item.source_path == Path("sample_01.png")
    assert preview_set.current_variant.recipe == "WebP q85"

    # Cycle variants with wrapping
    preview_set.next_variant()
    assert preview_set.current_variant.recipe == "WebP q70"
    preview_set.next_variant()
    assert preview_set.current_variant.recipe == "WebP q85"
    preview_set.prev_variant()
    assert preview_set.current_variant.recipe == "WebP q70"

    # Cycle images with wrapping
    preview_set.next_image()
    assert preview_set.current_item.source_path == Path("sample_02.png")
    preview_set.next_image()
    assert preview_set.current_item.source_path == Path("sample_01.png")
    preview_set.prev_image()
    assert preview_set.current_item.source_path == Path("sample_02.png")


def test_scan_preview_directory_with_manifest(tmp_path: Path):
    run_dir = tmp_path / "preview-20261019-050000-12345678"
    run_dir.mkdir(parents=True)

    orig_file = run_dir / "orig_01.png"
    orig_file.write_bytes(b"A" * 5000)

    webp_85 = run_dir / "candidate_01_webp85.webp"
    webp_85.write_bytes(b"B" * 2500)

    webp_70 = run_dir / "candidate_01_webp70.webp"
    webp_70.write_bytes(b"C" * 1500)

    manifest = {
        "schema": 1,
        "status": "completed",
        "output_directory": str(run_dir),
        "images": [
            {
                "source": str(orig_file),
                "status": "completed",
                "variants": [
                    {
                        "name": "webp-lossy-q85",
                        "format": "webp",
                        "mode": "lossy",
                        "quality": 85,
                        "output": str(webp_85),
                        "bytes": 2500,
                        "original_bytes": 5000,
                    },
                    {
                        "name": "webp-lossy-q70",
                        "format": "webp",
                        "mode": "lossy",
                        "quality": 70,
                        "output": str(webp_70),
                        "bytes": 1500,
                        "original_bytes": 5000,
                    },
                ],
            }
        ],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Scanning the run directory directly
    ps = scan_preview_directory(run_dir)
    assert len(ps.items) == 1
    item = ps.items[0]
    assert item.source_path == orig_file
    assert len(item.variants) == 2
    assert item.variants[0].recipe == "WebP lossy 85"
    assert item.variants[0].size_bytes == 2500
    assert item.variants[0].savings_percent == 50.0
    assert item.variants[1].recipe == "WebP lossy 70"
    assert item.variants[1].savings_percent == 70.0

    # Scanning the parent directory automatically finds the latest preview run
    ps_parent = scan_preview_directory(tmp_path)
    assert len(ps_parent.items) == 1
    assert ps_parent.items[0].source_path == orig_file
