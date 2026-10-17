from __future__ import annotations

from pathlib import Path
from compresser.cache import AnalysisCache
from compresser.models import CompressionStrategy, ImageResult


def test_cache_set_and_get(tmp_path: Path):
    dummy_file = tmp_path / "test.jpg"
    dummy_file.write_bytes(b"1234567890")

    cache = AnalysisCache()
    strat = CompressionStrategy(name="test", format="webp", mode="lossy", quality=80)
    res = ImageResult(
        input_path=dummy_file,
        output_path=dummy_file.with_suffix(".webp"),
        original_bytes=10,
        compressed_bytes=5,
        original_format="JPEG",
        output_format="WEBP",
        ssim=0.99,
        elapsed_s=0.01,
    )

    assert cache.get(dummy_file, strat) is None
    cache.set(dummy_file, strat, res)

    cached = cache.get(dummy_file, strat)
    assert cached is not None
    assert cached.compressed_bytes == 5
    assert cached.ssim == 0.99
