from dataclasses import replace
import json

import pytest
from PIL import Image

from cli_test_support import main
from compresser.models import ImageMetadata, ImageResult
from compresser.sampling import confirmation_sample, gallery_sample


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
    small_sample = gallery_sample(images, tmp_path, sample_size=2)
    assert len(small_sample.images) == 2
    assert small_sample.summary()["sampled_galleries"] == 2


def test_sampling_refuses_noncanonical_parent_paths(tmp_path):
    image = ImageMetadata(tmp_path / ".." / tmp_path.name / "01.jpg", "JPEG", 40, 40, 100)
    with pytest.raises(ValueError, match="canonical"):
        gallery_sample([image], tmp_path)


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


def test_increasing_budget_never_replaces_samples(tmp_path):
    images = population(tmp_path)
    prior = set()
    for size in range(3, len(images) + 1):
        plan = gallery_sample(images, tmp_path, sample_size=size, seed=42)
        selected = {i.path for i in plan.images}
        assert prior <= selected
        assert len(selected) == size
        prior = selected


def test_saved_sample_tracks_population_and_selection(tmp_path):
    import sqlite3
    from compresser.inventory import InventoryStore
    from compresser.scanner import scan_directory

    root = tmp_path / "library"
    root.mkdir()
    for i in range(4):
        Image.new("RGB", (40, 40)).save(root / f"{i}.png")
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    _, images = scan_directory(root, inventory=store)
    small = store.save_sample(gallery_sample(images, root, sample_size=2), root)
    large = store.save_sample(gallery_sample(images, root, sample_size=3), root)
    assert small["population_identity"] == large["population_identity"]
    with sqlite3.connect(store.path) as connection:
        reports = [
            json.loads(row[0]) for row in connection.execute("SELECT report FROM inventory_samples ORDER BY count")
        ]
    assert set(reports[0]["selected_files"]) < set(reports[1]["selected_files"])


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
    for extra in (["-w"], ["-P", "nan"]):
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


def test_coverage_gaps_rare_format_large_and_tall_images(tmp_path):
    images = [ImageMetadata(tmp_path / "g1" / f"{i:02d}.jpg", "JPEG", 80, 80, 100) for i in range(18)] + [
        ImageMetadata(tmp_path / "g1" / "large.jpg", "JPEG", 80, 80, 50_000),
        ImageMetadata(tmp_path / "g1" / "rare.gif", "GIF", 80, 80, 200),
        ImageMetadata(tmp_path / "g1" / "tall.png", "PNG", 80, 17_000, 500),
    ]
    # Find a seed where sample_size=1 picks one of the ordinary 100-byte JPEGs
    plan = next(
        candidate
        for s in range(50)
        if (candidate := gallery_sample(images, tmp_path, sample_size=1, seed=s)).images[0].size_bytes == 100
    )
    summary = plan.summary()
    assert summary["coverage_minimum_images"] == 1
    assert summary["variance_minimum_images"] == 2
    assert "GIF" in summary["unsampled_formats"]
    assert "PNG" in summary["unsampled_formats"]
    assert summary["sampled_large_images"] == 0
    assert summary["unsampled_large_images"] >= 1
    assert summary["unsampled_tall_webp_images"] == 1
    assert "unsampled_format:GIF" in summary["coverage_gaps"]
    assert "unsampled_top_decile_large_images" in summary["coverage_gaps"]
    assert "unsampled_webp_dimension_limit_images" in summary["coverage_gaps"]
    assert "singleton_non_census_galleries" in summary["coverage_gaps"]


def test_pilot_advisor_and_disjoint_confirmation_sample(tmp_path):
    images = [ImageMetadata(tmp_path / "steady" / f"{i:03d}.jpg", "JPEG", 80, 80, 10_000) for i in range(40)] + [
        ImageMetadata(tmp_path / "volatile" / f"{i:03d}.jpg", "JPEG", 80, 80, 10_000) for i in range(40)
    ]
    pilot = gallery_sample(images, tmp_path, sample_size=6, seed=7)
    pilot_results = []
    for idx, img in enumerate(pilot.images):
        if "steady" in str(img.path):
            saved = 4_000 + (idx % 2) * 10
        else:
            saved = 1_000 if idx % 2 == 0 else 8_000
        pilot_results.append(
            ImageResult(
                img.path,
                img.path,
                img.size_bytes,
                img.size_bytes - saved,
                img.format,
                img.format,
                elapsed_s=0.025,
            )
        )
    advisor = pilot.advise_sample_size(pilot_results, target_margin_percent=2.0, max_runtime_seconds=10.0)
    assert advisor["precision_met"] is False
    assert advisor["recommended_total_samples"] > len(pilot.images)
    assert advisor["recommended_additional_confirmation_samples"] > 0
    steady_key = str(tmp_path / "steady")
    volatile_key = str(tmp_path / "volatile")
    assert advisor["recommended_quotas"][volatile_key] > advisor["recommended_quotas"][steady_key]
    assert "confirmation" in advisor["adaptive_stopping_note"].lower()

    est = pilot.estimate(pilot_results)
    assert est["pilot_advisor"]["recommended_total_samples"] == advisor["recommended_total_samples"]
    assert est["approximate_95_percent_interval_bytes"] is not None
    assert est["two_stage_adjusted_95_percent_interval_bytes"] is None

    confirm = confirmation_sample(pilot, tmp_path, sample_size=12, pilot_results=pilot_results)
    assert len(confirm.images) == 12
    assert {i.path for i in pilot.images}.isdisjoint({i.path for i in confirm.images})
    confirm_results = [
        ImageResult(i.path, i.path, i.size_bytes, i.size_bytes - 4_500, i.format, i.format, elapsed_s=0.020)
        for i in confirm.images
    ]
    confirm_est = confirm.estimate(confirm_results)
    assert confirm_est["sampling_stage"] == "disjoint_confirmation"
    assert confirm_est["projected_total_saved_bytes"] == 362010


def test_repeated_sampling_simulation_unbiasedness_and_interval_coverage(tmp_path):
    galleries = [
        ("g_small", 20, 2_000, 600, 120),
        ("g_med", 50, 5_000, 2_000, 500),
        ("g_large", 80, 10_000, 4_500, 1_200),
    ]
    images = []
    true_saved_by_path = {}
    for folder, count, size, base_saved, spread in galleries:
        for i in range(count):
            path = tmp_path / folder / f"{i:03d}.jpg"
            images.append(ImageMetadata(path, "JPEG", 100, 100, size))
            offset = ((i * 7 + 3) % 11 - 5) / 5.0
            true_saved_by_path[path] = round(base_saved + spread * offset)

    true_total = sum(true_saved_by_path.values())
    estimates = []
    covered_standard = 0
    runs = 150
    for seed in range(runs):
        plan = gallery_sample(images, tmp_path, sample_size=30, seed=seed)
        results = [
            ImageResult(
                i.path,
                i.path,
                i.size_bytes,
                i.size_bytes - true_saved_by_path[i.path],
                i.format,
                i.format,
                elapsed_s=0.010,
            )
            for i in plan.images
        ]
        est = plan.estimate(results)
        estimates.append(est["projected_total_saved_bytes"])
        lo, hi = est["approximate_95_percent_interval_bytes"]
        if lo <= true_total <= hi:
            covered_standard += 1
        assert est["two_stage_adjusted_95_percent_interval_bytes"] is None

    mean_estimate = sum(estimates) / len(estimates)
    assert abs(mean_estimate - true_total) / true_total < 0.01
    assert covered_standard / runs >= 0.90


def test_parse_sample_percentages_and_validation():
    import argparse
    from compresser.sampling import parse_sample

    assert parse_sample("10%") == "10%"
    assert parse_sample("2.5%") == "2.5%"
    assert parse_sample("100%") == "100%"
    assert parse_sample("auto") == "auto"
    assert parse_sample("50") == 50

    with pytest.raises(argparse.ArgumentTypeError):
        parse_sample("0%")
    with pytest.raises(argparse.ArgumentTypeError):
        parse_sample("105%")
    with pytest.raises(argparse.ArgumentTypeError):
        parse_sample("0")
    with pytest.raises(argparse.ArgumentTypeError):
        parse_sample("-5")

