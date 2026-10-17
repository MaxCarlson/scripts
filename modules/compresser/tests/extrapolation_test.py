from dataclasses import replace
from pathlib import Path

import pytest

from compresser.models import ImageMetadata, ImageResult


def meta(name, size, fmt="JPEG"):
    return ImageMetadata(Path(name), fmt, 20, 20, size)


def trial(image, retained, **kwargs):
    return ImageResult(image.path, image.path, image.size_bytes, retained, image.format, "WEBP", **kwargs)


def extrapolate(population, selected, results, complete=True):
    from compresser.extrapolation import extrapolate_target

    return extrapolate_target(population, selected, results, complete=complete)


def test_byte_ratio_not_mean_percentage():
    a, b, c = meta("a", 100), meta("b", 900), meta("c", 200, "PNG")
    pop = [a, b, c, meta("d", 9000), meta("e", 1800, "PNG")]
    r = extrapolate(pop, [a, b, c], [trial(a, 50), trial(b, 900), trial(c, 100)])
    assert r["saved_bytes"] == 1500 and r["retained_bytes"] == 10500
    assert r["reduction_percent"] == 12.5 and r["status"] == "estimated"


def test_unsampled_format_uses_marked_overall_ratio():
    a = meta("a", 100)
    pop = [a, meta("b", 900), meta("c", 1000, "WEBP")]
    r = extrapolate(pop, [a], [trial(a, 50)])
    assert r["saved_bytes"] == 1000
    assert r["fallback_bytes"] == 1000 and r["fallback_percent"] == 50
    assert r["formats"]["WEBP"]["basis"] == "overall-ratio fallback"


def test_failures_stay_in_denominator_and_cache_does_not_change_estimate():
    a, b = meta("a", 100), meta("b", 100)
    trials = [trial(a, 50), trial(b, 0, error="cannot decode")]
    r = extrapolate([a, b], [a, b], trials)
    assert r["saved_bytes"] == 50 and r["retained_bytes"] == 150
    assert r["failed_count"] == 1 and r["status"] == "calculated"
    assert extrapolate([a, b], [a, b], [replace(t, cache_hit=True) for t in trials]) == r


def test_all_failed_zero_scenario_not_positive_evidence():
    a = meta("a", 100)
    r = extrapolate([a], [a], [trial(a, 0, error="failed")])
    assert r["saved_bytes"] == 0 and r["successful_count"] == 0
    assert "no successful encodes" in " ".join(r["warnings"])


def test_signed_growth_and_partial_census():
    a, b = meta("a", 100), meta("b", 100)
    r = extrapolate([a, b], [a, b], [trial(a, 120)], complete=False)
    assert r["saved_bytes"] == -40 and r["retained_bytes"] == 240
    assert r["status"] == "partial"
    assert extrapolate([a], [a], [trial(a, 120)])["saved_bytes"] == -20


def test_zero_bytes_empty_and_JPG_alias():
    assert extrapolate([], [], [])["saved_bytes"] is None
    z = meta("z", 0)
    assert extrapolate([z], [z], [trial(z, 0)])["saved_bytes"] is None
    a, b = meta("a", 100, "JPG"), meta("b", 100)
    r = extrapolate([a, b], [a], [trial(a, 50)])
    assert list(r["formats"]) == ["JPEG"] and r["saved_bytes"] == 100


def test_duplicate_foreign_or_mismatched_results_rejected():
    a, b = meta("a", 100), meta("b", 100)
    for results in ([trial(a, 50), trial(a, 50)], [trial(b, 50)], [replace(trial(a, 50), original_bytes=10)]):
        with pytest.raises(ValueError):
            extrapolate([a, b], [a], results)
