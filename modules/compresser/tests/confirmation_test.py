from dataclasses import replace

import pytest

from compresser.models import ImageMetadata, ImageResult
from compresser.sampling import confirmation_sample, gallery_sample


def _result(image, saved):
    return ImageResult(image.path, image.path, image.size_bytes, image.size_bytes - saved, image.format, image.format)


def _pilot(root, *, singleton=False):
    images = [ImageMetadata(root / "manga" / f"{n}.jpg", "JPEG", 40, 40, 1000) for n in range(4)]
    if singleton:
        images.append(ImageMetadata(root / "single" / "0.jpg", "JPEG", 40, 40, 1000))
    pilot = gallery_sample(images, root, sample_size=3 if singleton else 2)
    observations = [_result(image, 50 if image.path.parent.name == "single" else 900) for image in pilot.images]
    return pilot, observations


@pytest.mark.parametrize("singleton,total", [(False, 2000), (True, 2050)])
def test_confirmation_census_adds_pilot_totals(tmp_path, singleton, total):
    pilot, observations = _pilot(tmp_path, singleton=singleton)
    confirm = confirmation_sample(pilot, tmp_path, sample_size=2, pilot_results=observations)
    report = confirm.estimate([_result(image, 100) for image in confirm.images])
    assert report["projected_total_saved_bytes"] == total
    assert report["approximate_95_percent_interval_bytes"] == [total, total]
    assert report["unestimated_images"] == 0


@pytest.mark.parametrize("damage", ["missing", "failed", "duplicate", "wrong_size"])
def test_confirmation_refuses_unreliable_pilot_observations(tmp_path, damage):
    pilot, observations = _pilot(tmp_path)
    if damage == "missing":
        observations.pop()
    elif damage == "failed":
        observations[0] = replace(observations[0], error="failed")
    elif damage == "duplicate":
        observations.append(observations[0])
    else:
        observations[0] = replace(observations[0], original_bytes=1001)
    with pytest.raises(ValueError, match="pilot"):
        confirmation_sample(pilot, tmp_path, sample_size=2, pilot_results=observations)


def test_confirmation_requires_observed_pilot_not_just_selected_paths(tmp_path):
    pilot, _ = _pilot(tmp_path)
    with pytest.raises(ValueError, match="pilot"):
        confirmation_sample(pilot, tmp_path, sample_size=2)


def test_confirmation_missing_results_preserves_known_pilot_only(tmp_path):
    pilot, observations = _pilot(tmp_path)
    confirm = confirmation_sample(pilot, tmp_path, sample_size=2, pilot_results=observations)
    report = confirm.estimate([])
    assert report["projected_total_saved_bytes"] is None
    assert report["projected_covered_saved_bytes"] == 1800
    assert report["unestimated_images"] == 2
    assert report["approximate_95_percent_interval_bytes"] is None


def test_no_interval_claim_for_arbitrary_outcome_adaptive_pooling(tmp_path):
    pilot, observations = _pilot(tmp_path)
    report = pilot.estimate(observations)
    assert report["two_stage_adjusted_95_percent_interval_bytes"] is None
    note = report["pilot_advisor"]["adaptive_stopping_note"]
    assert "do not pool" in note.lower()


def test_confirmation_uses_remaining_population_finite_correction(tmp_path):
    images = [ImageMetadata(tmp_path / "manga" / f"{n}.jpg", "JPEG", 40, 40, 1000) for n in range(6)]
    pilot = gallery_sample(images, tmp_path, sample_size=2)
    confirm = confirmation_sample(pilot, tmp_path, sample_size=2, pilot_results=[_result(i, 900) for i in pilot.images])
    report = confirm.estimate([_result(confirm.images[0], 100), _result(confirm.images[1], 300)])
    assert report["projected_total_saved_bytes"] == 2600
    assert report["approximate_95_percent_interval_bytes"] == [2046, 3154]


def test_confirmation_rejects_duplicate_result_instead_of_silently_overwriting(tmp_path):
    pilot, observations = _pilot(tmp_path)
    confirm = confirmation_sample(pilot, tmp_path, sample_size=2, pilot_results=observations)
    result = _result(confirm.images[0], 100)
    with pytest.raises(ValueError, match="duplicate"):
        confirm.estimate([result, result])


def test_conditional_estimator_simulation_with_pilot_driven_confirmation_size(tmp_path):
    images = [ImageMetadata(tmp_path / "manga" / f"{n}.jpg", "JPEG", 40, 40, 2000) for n in range(24)]
    savings = {image.path: 200 + 60 * n for n, image in enumerate(images)}
    estimates, covered = [], 0
    for seed in range(300):
        pilot = gallery_sample(images, tmp_path, sample_size=4, seed=seed)
        measured = [_result(image, savings[image.path]) for image in pilot.images]
        # Allocation depends on pilot outcomes, never confirmation outcomes.
        count = 8 if sum(result.saved_bytes for result in measured) > 4000 else 12
        confirm = confirmation_sample(pilot, tmp_path, sample_size=count, pilot_results=measured)
        report = confirm.estimate([_result(image, savings[image.path]) for image in confirm.images])
        estimates.append(report["projected_total_saved_bytes"])
        low, high = report["approximate_95_percent_interval_bytes"]
        covered += low <= 21360 <= high
    assert abs(sum(estimates) / len(estimates) - 21360) < 427.2  # 2% of the literal fixture truth.
    assert covered / 300 >= 0.90  # Diagnostic for this fixture, not a general accuracy guarantee.


def test_cli_does_not_advertise_an_unapplied_precision_allocation(tmp_path, capsys):
    from PIL import Image
    from cli_test_support import main

    for n in range(3):
        Image.new("RGB", (40, 40)).save(tmp_path / f"{n}.png")
    assert main(["-i", str(tmp_path), "-s", "1", "-f", "png", "-e", "0", "-N"]) == 0
    output = capsys.readouterr().out
    assert "recommend -s" not in output
    assert "not guaranteed savings" in " ".join(output.lower().split())
