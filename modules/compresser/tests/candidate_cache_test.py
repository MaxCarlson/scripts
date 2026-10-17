from dataclasses import replace

from PIL import Image
import pytest

from compresser.cache import AnalysisCache
from compresser.engine import CompressionEngine
from compresser.models import CompressionStrategy
from compresser.scanner import scan_directory


@pytest.mark.parametrize("mode", ["lossless", "lossy"])
def test_auto_reuses_explicit_candidates_without_encoding(tmp_path, monkeypatch, mode):
    Image.new("RGB", (80, 80), "white").save(tmp_path / "01.bmp")
    _, images = scan_directory(tmp_path)
    engine = CompressionEngine()
    engine.codecs.pop("cli-jpegtran", None)
    strategy = CompressionStrategy("comparison", mode=mode, method=0)
    reference = CompressionEngine().compress_image(images[0], strategy)
    for fmt in ("png", "webp", "jpeg"):
        engine.compress_image(
            images[0], replace(strategy, name=f"explicit-{fmt}", format=fmt, mode="lossless" if fmt == "png" else mode)
        )
    monkeypatch.setattr(engine, "_encode_verified", lambda *a: pytest.fail("AUTO encoded cached candidate"))
    result = engine.compress_image(images[0], replace(strategy, name="different-auto-label"))
    assert result.cache_hit
    assert (result.compressed_bytes, result.output_format, result.candidate_bytes) == (
        reference.compressed_bytes,
        reference.output_format,
        reference.candidate_bytes,
    )


def test_quality_change_invalidates_lossy_but_not_lossless(tmp_path, monkeypatch):
    Image.new("RGB", (80, 80), "white").save(tmp_path / "01.png")
    _, images = scan_directory(tmp_path)
    engine = CompressionEngine(AnalysisCache())
    strategy = CompressionStrategy("one", format="webp", mode="lossless", quality=80, method=0)
    engine.compress_image(images[0], strategy)
    assert engine.compress_image(images[0], replace(strategy, name="two", quality=75)).cache_hit
    assert engine.compress_image(images[0], replace(strategy, quality=0)).error
    lossy = replace(strategy, mode="lossy", quality=80)
    engine.compress_image(images[0], lossy)
    assert not engine.compress_image(images[0], replace(lossy, quality=75)).cache_hit
