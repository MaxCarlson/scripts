"""AUTO analysis caches verified evidence, never preview bytes or failed candidates."""

from dataclasses import replace

from PIL import Image
import pytest

from compresser import CompressionEngine, CompressionStrategy, scan_directory


@pytest.mark.parametrize("mode", ["lossless", "lossy"])
def test_auto_first_reuses_verified_explicit_candidates(tmp_path, monkeypatch, mode):
    Image.new("RGB", (64, 64), "navy").save(tmp_path / "01.png")
    _, images = scan_directory(tmp_path)
    engine = CompressionEngine()
    auto = CompressionStrategy("auto", format="auto", mode=mode, quality=80, method=0)
    try:
        first = engine.compress_batch(images, auto)
        assert first.failed_count == 0
        original = engine._encode_verified

        def forbidden(*args, **kwargs):
            pytest.fail("Re-encoded an AUTO candidate already verified in this analysis")

        monkeypatch.setattr(engine, "_encode_verified", forbidden)
        for fmt in ("webp", "png"):
            candidate = replace(auto, format=fmt, mode="lossless" if fmt == "png" else mode)
            result = engine.compress_batch(images, candidate)
            assert result.failed_count == 0 and result.results[0].cache_hit
        monkeypatch.setattr(engine, "_encode_verified", original)
    finally:
        engine.cache.close()


def test_auto_partial_failure_never_caches_failed_candidate(tmp_path, monkeypatch):
    Image.new("RGB", (64, 64), "navy").save(tmp_path / "01.png")
    _, images = scan_directory(tmp_path)
    engine = CompressionEngine()
    auto = CompressionStrategy("auto", method=0)
    original = engine._encode_verified

    def reader(image, fmt, strategy):
        if fmt == "png":
            raise ValueError("Encoder did not preserve exif metadata")
        return original(image, fmt, strategy)

    monkeypatch.setattr(engine, "_encode_verified", reader)
    try:
        assert engine.compress_batch(images, auto).failed_count == 0
        assert engine.cache.get(images[0].path, replace(auto, format="png")) is None
        assert engine.cache.get(images[0].path, replace(auto, format="webp")) is not None
    finally:
        engine.cache.close()


def test_explicit_first_auto_retains_same_result_without_encodes(tmp_path, monkeypatch):
    Image.new("RGB", (64, 64), "navy").save(tmp_path / "01.png")
    _, images = scan_directory(tmp_path)
    auto = CompressionStrategy("auto", mode="lossy", method=0)
    with CompressionEngine().cache as cache:
        engine = CompressionEngine(cache=cache)
        candidates = [
            engine.compress_batch(
                images, replace(auto, format=fmt, mode="lossless" if fmt == "png" else auto.mode)
            ).results[0]
            for fmt in ("webp", "png", "jpeg")
        ]

        def forbidden(*a, **k):
            pytest.fail("AUTO re-encoded fully cached formats")

        monkeypatch.setattr(engine, "_encode_verified", forbidden)
        result = engine.compress_batch(images, auto).results[0]
        best = min(candidates, key=lambda item: item.candidate_bytes)
        assert result.cache_hit
        assert (result.compressed_bytes, result.output_format, result.ssim) == (
            best.compressed_bytes,
            best.output_format,
            best.ssim,
        )


def test_source_change_before_candidate_publication_does_not_cache(tmp_path, monkeypatch):
    path = tmp_path / "01.png"
    Image.new("RGB", (64, 64), "navy").save(path)
    _, images = scan_directory(tmp_path)
    engine = CompressionEngine()
    strategy = CompressionStrategy("auto", method=0)
    original = engine._encode_verified

    def changed(*a, **k):
        result = original(*a, **k)
        path.write_bytes(path.read_bytes() + b"changed")
        return result

    monkeypatch.setattr(engine, "_encode_verified", changed)
    try:
        result = engine.compress_batch(images, strategy)
        assert result.failed_count == 1
        assert engine.cache.get(path, replace(strategy, format="webp")) is None
    finally:
        engine.cache.close()
