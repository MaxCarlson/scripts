"""Measured selection, encoder control and persistent inventory/trial cache."""

from __future__ import annotations

from dataclasses import replace

import pytest
from PIL import Image

from compresser import AnalysisCache, CompressionEngine, CompressionStrategy, scan_directory
from compresser.cli import main, run_comparison


def test_lossless_growth_is_measured_but_original_retained(tmp_path, capsys):
    import random
    from compresser.ui import print_comparison_matrix

    source = tmp_path / "001.jpg"
    Image.frombytes("RGB", (80, 80), random.Random(42).randbytes(80 * 80 * 3)).save(source, quality=70)
    before = source.read_bytes()
    _, images = scan_directory(tmp_path)
    engine = CompressionEngine()
    engine.codecs.pop("cli-jpegtran", None)
    rows = run_comparison(images, engine, no_ui=True)
    png = rows[0]
    assert png.candidate_bytes > png.original_bytes
    assert png.saved_bytes == 0 and png.skipped_count == 1 and png.failed_count == 0
    assert png.compressed_bytes == len(before)
    assert rows[2].failed_count == 1 and rows[2].candidate_bytes is None
    assert rows[2].error_summary
    print_comparison_matrix(rows)
    output = capsys.readouterr().out
    assert "Savings use retained size" in output and "Kept excludes failures" in output
    assert "encoded candidates" in output and "failed:" in output
    assert "\x1b[" not in output
    assert source.read_bytes() == before


def test_png_is_actual_lossless_png(tmp_path):
    source = tmp_path / "001.bmp"
    Image.new("RGBA", (80, 80), (10, 100, 200, 120)).save(source)
    _, images = scan_directory(tmp_path)
    result = CompressionEngine().compress_image(
        images[0], CompressionStrategy("png", format="png", mode="lossless"), write_mode=True
    )
    assert result.applied and result.encoder == "pillow-png"
    with Image.open(result.output_path) as output:
        assert output.format == "PNG"


def test_auto_matches_smallest_valid_candidate(tmp_path):
    source = tmp_path / "001.bmp"
    Image.new("RGB", (80, 80), (10, 100, 200)).save(source)
    _, images = scan_directory(tmp_path)
    engine = CompressionEngine()
    strategy = CompressionStrategy("test", mode="lossless")
    candidates = [engine.compress_image(images[0], replace(strategy, format=fmt)) for fmt in ("png", "webp", "jpeg")]
    smallest = min((r for r in candidates if not r.error), key=lambda r: r.compressed_bytes)
    result = engine.compress_image(images[0], strategy)
    assert result.compressed_bytes == smallest.compressed_bytes
    assert result.output_format == smallest.output_format
    assert result.encoder == smallest.encoder
    assert source.exists()


def test_encoder_choice_invalidates_cache(tmp_path):
    source = tmp_path / "001.bmp"
    Image.new("RGB", (80, 80)).save(source)
    _, images = scan_directory(tmp_path)
    cache = AnalysisCache()
    engine = CompressionEngine(cache)
    good = CompressionStrategy("same", format="webp", mode="lossless", encoder="pillow-webp")
    first = engine.compress_image(images[0], good)
    assert not first.error
    invalid = engine.compress_image(images[0], replace(good, encoder="pillow-jpeg"))
    assert invalid.error and not invalid.cache_hit


def test_trial_persists_across_engines(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    source = library / "001.bmp"
    Image.new("RGB", (80, 80)).save(source)
    _, images = scan_directory(library)
    path = tmp_path / "separate-cache.sqlite3"
    strategy = CompressionStrategy("same", format="webp", mode="lossless")
    first = CompressionEngine(AnalysisCache(path=path)).compress_image(images[0], strategy)
    second = CompressionEngine(AnalysisCache(path=path))

    def forbidden(*args):
        pytest.fail("Encoded instead of using persistent trial")

    monkeypatch.setattr(second, "_encode_verified", forbidden)
    result = second.compress_image(images[0], strategy)
    assert result.cache_hit and result.compressed_bytes == first.compressed_bytes
    changed = replace(strategy, method=1)
    assert second.cache.get(source, changed) is None
    source.write_bytes(source.read_bytes() + b"changed")
    assert second.cache.get(source, strategy) is None


def test_inventory_cache_skips_unchanged_headers(tmp_path, monkeypatch):
    import compresser.scanner as scanner

    library = tmp_path / "library"
    library.mkdir()
    Image.new("RGB", (80, 80)).save(library / "001.jpg")
    path = tmp_path / "cache.sqlite3"
    first, _ = scan_directory(library, cache=AnalysisCache(path=path))

    def forbidden(*args, **kwargs):
        pytest.fail("Opened unchanged image header")

    monkeypatch.setattr(scanner, "inspect_image_file", forbidden)
    second, _ = scan_directory(library, cache=AnalysisCache(path=path))
    assert second == first


def test_cache_refused_inside_input(tmp_path):
    Image.new("RGB", (80, 80)).save(tmp_path / "001.jpg")
    assert main(["-i", str(tmp_path), "-K", str(tmp_path / "cache.sqlite3"), "-N"]) == 2
    assert not (tmp_path / "cache.sqlite3").exists()


def test_comparison_respects_lossless_and_reports_failures(tmp_path):
    Image.new("RGB", (80, 80)).save(tmp_path / "001.jpg")
    _, images = scan_directory(tmp_path)
    rows = run_comparison(images, CompressionEngine(), no_ui=True)
    assert all(row.mode == "lossless" for row in rows)
    assert all(row.measured_images == 1 for row in rows)
    engine = CompressionEngine()
    engine.codecs.pop("cli-jpegtran", None)
    rows = run_comparison(images, engine, no_ui=True)
    assert next(row for row in rows if row.output_format == "jpeg").failed_count == 1


def test_sample_balances_formats_and_estimate_marks_uncovered(tmp_path):
    from compresser.models import ImageMetadata, ImageResult
    from compresser.scanner import select_sample
    from compresser.estimates import estimate_savings

    images = [ImageMetadata(tmp_path / f"{n}.jpg", "JPEG", 80, 80, 100) for n in range(10)]
    images.append(ImageMetadata(tmp_path / "rare.webp", "WEBP", 80, 80, 100))
    sample = select_sample(images, 2)
    assert {item.format for item in sample} == {"JPEG", "WEBP"}

    def result(image):
        return ImageResult(image.path, image.path, image.size_bytes, 50, image.format, image.format)

    estimate = estimate_savings(images, [result(item) for item in sample])
    assert estimate["projected_total_saved_bytes"] == 550
    assert estimate["measured_saved_bytes"] == 100
    incomplete = estimate_savings(images, [result(sample[0])])
    assert incomplete["projected_total_saved_bytes"] is None
    assert incomplete["unestimated_images"] > 0
