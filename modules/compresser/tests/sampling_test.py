from dataclasses import replace
import json

import pytest
from PIL import Image

from compresser.cli import main
from compresser.models import ImageMetadata, ImageResult
from compresser.sampling import gallery_sample


def population(root):
    return [
        ImageMetadata(root / folder / f"{i}.jpg", "JPEG", 80, 80, size)
        for folder, count, size in [("small", 10, 100), ("large", 100, 1000), ("tiny", 1, 50)]
        for i in range(count)
    ]


def test_coverage_weights_seed_and_percentage(tmp_path):
    images = population(tmp_path)
    plan = gallery_sample(images, tmp_path, sample_size=30, seed=8)
    assert len(plan.images) == 30
    assert len({i.path for i in plan.images}) == 30
    assert plan.summary()["sampled_galleries"] == 3
    assert plan.quotas[str(tmp_path / "large")] > plan.quotas[str(tmp_path / "small")]
    assert plan.images == gallery_sample(list(reversed(images)), tmp_path, sample_size=30, seed=8).images
    assert plan.images != gallery_sample(images, tmp_path, sample_size=30, seed=9).images
    assert len(gallery_sample(images, tmp_path, percent=10).images) == 12
    assert len(gallery_sample(images, tmp_path, percent=0.01).images) == 3
    with pytest.raises(ValueError, match="cannot cover"):
        gallery_sample(images, tmp_path, sample_size=2)


def test_weighted_estimate_failures_and_uncertainty(tmp_path):
    images = population(tmp_path)
    plan = gallery_sample(images, tmp_path, sample_size=30)
    results = [ImageResult(i.path, i.path, i.size_bytes, i.size_bytes // 2, i.format, i.format) for i in plan.images]
    report = plan.estimate(results)
    assert report["projected_total_saved_bytes"] == 50525
    assert report["approximate_95_percent_interval_bytes"] == [50525, 50525]
    results[0] = replace(results[0], error="failed")
    assert plan.estimate(results)["projected_total_saved_bytes"] is None
    singleton = gallery_sample(images, tmp_path, sample_size=3)
    assert singleton.estimate([])["approximate_95_percent_interval_bytes"] is None


def test_combined_cli_and_persistent_cache(tmp_path, capsys):
    gallery = tmp_path / "library" / "gallery"
    gallery.mkdir(parents=True)
    Image.new("RGB", (80, 80), "white").save(gallery / "01.png")
    args = [
        "-i",
        str(gallery.parent),
        "-b",
        "-q",
        "80",
        "-P",
        "10",
        "-e",
        "0",
        "-J",
        "-K",
        str(tmp_path / "cache.sqlite3"),
    ]
    assert main(args) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 7
    assert {r["mode"] for r in rows} == {"lossless", "lossy"}
    assert {r["measured_images"] for r in rows} == {1}
    assert all(r["sampling"]["sampled_galleries"] == 1 for r in rows)
    assert main(args) == 0
    cached = json.loads(capsys.readouterr().out)
    assert any(r["cache_hits"] for r in cached)
    for extra in (["-s", "1"], ["-w"], ["-P", "nan"]):
        with pytest.raises(SystemExit):
            main(args + extra)


def test_cache_is_persisted_before_batch_finishes(tmp_path):
    from compresser.cache import AnalysisCache
    from compresser.engine import CompressionEngine
    from compresser.models import CompressionStrategy
    from compresser.scanner import scan_directory

    library = tmp_path / "gallery"
    library.mkdir()
    for i in range(3):
        Image.new("RGB", (40, 40), "white").save(library / f"{i}.png")
    _, images = scan_directory(library)
    cache_path = tmp_path / "cache.sqlite3"
    strategy = CompressionStrategy(name="live-cache", format="webp", mode="lossless", method=0)
    seen = []

    def completed(done, total, result):
        cached = AnalysisCache(path=cache_path).get(result.input_path, strategy)
        assert cached is not None and cached.cache_hit
        seen.append(done < total)

    CompressionEngine(cache=AnalysisCache(path=cache_path)).compress_batch(
        images, strategy, threads=1, progress_callback=completed
    )
    assert any(seen)
