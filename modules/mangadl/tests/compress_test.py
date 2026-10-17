from __future__ import annotations

import json
import pytest
from pathlib import Path
from PIL import Image

from mangadl.cli import build_parser, main
from mangadl.compress import discover_gallery_targets
from mangadl.destination_audit import _validate_image, _inspect_pages


def test_inventory_only_reuses_nested_headers(tmp_path, capsys, monkeypatch):
    import compresser.scanner as scanner

    root = tmp_path / "library"
    gallery = root / "manga" / "chapter"
    gallery.mkdir(parents=True)
    Image.new("RGB", (40, 40)).save(gallery / "01.png")
    Image.new("RGB", (40, 40)).save(gallery / "cover.png")
    args = ["compress", "-d", str(root), "-l", "-I", str(tmp_path / "inventory.sqlite3")]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["images"] == 1
    assert report["galleries"][str(root / "manga")]["images"] == 1
    monkeypatch.setattr(scanner, "inspect_image_file", lambda *a, **k: pytest.fail("Unchanged header reopened"))
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["headers_reused"] >= 2


def test_combined_gallery_sample_report(tmp_path, capsys):
    for gallery in ("small", "large"):
        directory = tmp_path / gallery / "chapter"
        directory.mkdir(parents=True)
        for i in range(3 if gallery == "small" else 9):
            Image.new("RGB", (40, 40), "white").save(directory / f"{i}.png")
    assert main(["compress", "-d", str(tmp_path), "-b", "-P", "50", "-q", "75", "-e", "0", "-J"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 7
    assert all(row["sampling"]["galleries"] == 2 for row in rows)
    assert all(row["measured_images"] == 6 for row in rows)
    assert all("estimate" in row for row in rows)


def test_compress_cli_help(capsys):
    import pytest

    parser = build_parser(["compress", "--help"])
    assert parser is not None
    with pytest.raises(SystemExit) as result:
        parser.parse_args(["compress", "--help"])
    assert result.value.code == 0
    assert "N images total" in capsys.readouterr().out


def test_compress_interrupt_returns_130(tmp_path, monkeypatch, capsys):
    from compresser import CompressionEngine

    Image.new("RGB", (40, 40)).save(tmp_path / "001.png")

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(CompressionEngine, "compress_batch", interrupt)
    assert main(["compress", "-d", str(tmp_path), "-N", "-J"]) == 130
    output = capsys.readouterr()
    assert output.out == "" and "Cancelled" in output.err


def test_discover_gallery_targets(tmp_path: Path):
    dest = tmp_path / "library"
    dest.mkdir()
    gal1 = dest / "manga-1"
    gal1.mkdir()
    im = Image.new("RGB", (100, 100), color=(10, 20, 30))
    im.save(gal1 / "001.jpg", format="JPEG")

    gal2 = dest / "manga-2"
    gal2.mkdir()
    im.save(gal2 / "001.jpg", format="JPEG")

    hidden = dest / ".mangadl"
    hidden.mkdir()

    targets = discover_gallery_targets(dest)
    assert len(targets) == 2
    assert gal1 in targets
    assert gal2 in targets
    assert hidden not in targets


def test_compress_dry_run(tmp_path: Path, capsys):
    dest = tmp_path / "library"
    dest.mkdir()
    gal = dest / "series-a"
    gal.mkdir()
    im = Image.new("RGB", (120, 120), color=(50, 100, 150))
    src = gal / "001.jpg"
    im.save(src, format="JPEG", quality=85)

    ret = main(["compress", "-d", str(dest), "-f", "webp", "-m", "perceptual", "-N"])
    assert ret == 0

    # Ensure dry run did not touch original file
    assert src.exists()
    assert not (gal / "001.webp").exists()


def test_compress_write_mode_and_audit(tmp_path: Path):
    dest = tmp_path / "library"
    dest.mkdir()
    gal = dest / "series-b"
    gal.mkdir()

    # Create two pages
    im = Image.new("RGB", (120, 120), color=(80, 120, 160))
    im.save(gal / "001.jpg", format="JPEG", quality=90)
    im.save(gal / "002.jpg", format="JPEG", quality=90)

    # Sidecar file
    (gal / "info.json").write_text('{"title": "B"}', encoding="utf-8")

    # Apply compression (with explicit -L / --allow-lossy)
    ret = main(["compress", "-d", str(dest), "-f", "webp", "-m", "lossy", "-q", "75", "-w", "-L", "-N"])
    assert ret == 0

    # Check files
    assert not (gal / "001.jpg").exists()
    assert not (gal / "002.jpg").exists()
    assert (gal / "001.webp").exists()
    assert (gal / "002.webp").exists()
    assert (gal / "info.json").exists()

    # Verify audit integrity: inspect_pages should see exactly valid pages 1 and 2, no duplicates
    findings = _inspect_pages(gal, expected_count=2, image_validator=_validate_image)
    assert findings["completeness"] == "complete"
    assert findings["image_integrity"] == "valid"
    assert findings["valid_images"] == 2
    assert len(findings["duplicate_pages"]) == 0
    assert len(findings["missing_pages"]) == 0


def test_compress_audit_defect_non_regression(tmp_path: Path):
    """Verify that compression introduces no new audit defects and preserves existing defect status."""
    dest = tmp_path / "library"
    dest.mkdir()
    gal = dest / "incomplete-series"
    gal.mkdir()

    # Create incomplete gallery: pages 1 and 3 exist, page 2 is missing
    im = Image.new("RGB", (100, 100), color=(10, 20, 30))
    im.save(gal / "001.jpg", format="JPEG", quality=90)
    im.save(gal / "003.jpg", format="JPEG", quality=90)

    # Pre-audit check
    findings_before = _inspect_pages(gal, expected_count=3, image_validator=_validate_image)
    assert findings_before["completeness"] == "incomplete"
    assert findings_before["missing_pages"] == [2]

    # Run compression with write mode
    ret = main(["compress", "-d", str(dest), "-f", "webp", "-m", "lossy", "-q", "75", "-w", "-L", "-N"])
    assert ret == 0

    # Post-audit check: incomplete status preserved, page 2 still missing, zero duplicate pages
    findings_after = _inspect_pages(gal, expected_count=3, image_validator=_validate_image)
    assert findings_after["completeness"] == "incomplete"
    assert findings_after["missing_pages"] == [2]
    assert len(findings_after["duplicate_pages"]) == 0
    assert findings_after["valid_images"] == 2
    assert findings_after["image_integrity"] == "valid"
    assert (gal / "001.webp").exists()
    assert (gal / "003.webp").exists()
    assert not (gal / "001.jpg").exists()
    assert not (gal / "003.jpg").exists()


def test_compress_compare_json(tmp_path: Path, capsys):
    dest = tmp_path / "library"
    dest.mkdir()
    gal = dest / "series-c"
    gal.mkdir()
    im = Image.new("RGB", (100, 100), color=(10, 20, 30))
    im.save(gal / "001.jpg", format="JPEG")

    ret = main(["compress", "-d", str(dest), "-c", "-J", "-N"])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, list)
    assert len(data) > 0
    assert any("strategy" in row for row in data)


def test_exact_url_selection_and_cover_exclusion(tmp_path):
    from mangadl.library_index import write_source_manifest

    destination = tmp_path / "library"
    gallery = destination / "renamed-gallery"
    gallery.mkdir(parents=True)
    Image.new("RGB", (40, 40)).save(gallery / "001.jpg")
    cover = gallery / "cover.jpg"
    Image.new("RGB", (40, 40)).save(cover)
    before = cover.read_bytes()
    write_source_manifest(gallery, "https://nhentai.net/g/633374/", "gallery-dl")
    assert discover_gallery_targets(destination, ["https://nhentai.net/g/633374/"]) == [gallery]
    import pytest

    with pytest.raises(ValueError, match="unresolved"):
        discover_gallery_targets(destination, ["renamed"])
    assert (
        main(["compress", "-d", str(destination), "-u", "https://nhentai.net/g/633374/", "-m", "lossless", "-w", "-N"])
        == 0
    )
    assert cover.read_bytes() == before


def test_active_repair_blocks_compression_write(tmp_path):
    root = tmp_path / "library"
    gallery = root / "gallery"
    gallery.mkdir(parents=True)
    Image.new("RGB", (40, 40)).save(gallery / "001.jpg")
    controls = root / ".mangadl"
    controls.mkdir()
    (controls / "repair.lock").write_text("active", encoding="utf-8")
    assert main(["compress", "-d", str(gallery), "-w", "-N"]) == 2
    assert (gallery / "001.jpg").exists()


def test_nested_gallery_selection_and_analysis(tmp_path, capsys):
    from mangadl.library_index import write_source_manifest

    root = tmp_path / "library"
    gallery = root / "series"
    chapter = gallery / "chapter-1"
    chapter.mkdir(parents=True)
    image = Image.new("RGB", (40, 40))
    page = chapter / "001.png"
    image.save(page)
    before = page.read_bytes()
    for directory in (gallery / ".controls", gallery / "_partial"):
        directory.mkdir()
        image.save(directory / "002.png")
    image.save(chapter / "cover.png")
    write_source_manifest(gallery, "https://nhentai.net/g/633374/", "gallery-dl")

    assert discover_gallery_targets(root) == [gallery]
    assert discover_gallery_targets(gallery) == [gallery]
    assert discover_gallery_targets(gallery, ["https://nhentai.net/g/633374/"]) == [gallery]
    assert main(["compress", "-d", str(root), "-J", "-N"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["inventory_images"] == 1
    assert result["total_images"] == 1
    assert page.read_bytes() == before
    assert not (chapter / ".compress.lock").exists()


def test_nested_gallery_write_preserves_chapter_paths(tmp_path):
    gallery = tmp_path / "library" / "series"
    for name in ("chapter-1", "chapter-2"):
        chapter = gallery / name
        chapter.mkdir(parents=True)
        Image.new("RGB", (120, 120), (80, 120, 160)).save(chapter / "001.jpg", quality=90)
    assert main(["compress", "-d", str(gallery.parent), "-f", "webp", "-m", "lossy", "-w", "-L", "-N"]) == 0
    for name in ("chapter-1", "chapter-2"):
        assert not (gallery / name / "001.jpg").exists()
        with Image.open(gallery / name / "001.webp") as image:
            image.load()
            assert image.size == (120, 120)
