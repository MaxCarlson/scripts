"""Conditional inference after a measured pilot and disjoint remaining-population sample."""

from __future__ import annotations

import math
from statistics import variance
from typing import Sequence

from .models import ImageMetadata, ImageResult


def validate_pilot_results(images: Sequence[ImageMetadata], results: Sequence[ImageResult] | None) -> None:
    """Require a successful, one-to-one measured pilot before conditional inference."""
    expected = {image.path: image for image in images}
    supplied = list(results or ())
    if len(expected) != len(images) or len(supplied) != len(expected):
        raise ValueError("Confirmation requires one successful result for every pilot image")
    seen = set()
    for result in supplied:
        image = expected.get(result.input_path)
        if (
            image is None
            or result.input_path in seen
            or result.error
            or result.original_bytes != image.size_bytes
            or result.compressed_bytes < 0
            or result.original_format.upper() != image.format.upper()
        ):
            raise ValueError("Invalid, duplicate, failed or mismatched pilot result")
        seen.add(result.input_path)


def estimate_confirmation(plan, results: Sequence[ImageResult]) -> dict:
    """Add known pilot totals to a stratified estimate over the remaining population.

    Conditional on the observed pilot, the residual population is fixed. Sampling
    all residual units therefore has zero sampling uncertainty even when the pilot
    was very different. A failed residual stratum remains explicitly unestimated.
    """
    validate_pilot_results(plan.pilot_images, plan.pilot_observations)
    pilot = {result.input_path: result for result in plan.pilot_observations}
    selected = {image.path: image for image in plan.images}
    if selected.keys() & pilot.keys():
        raise ValueError("Confirmation must be disjoint from the pilot")
    observed = {}
    for result in results:
        image = selected.get(result.input_path)
        if image is None or result.input_path in observed or result.original_bytes != image.size_bytes:
            raise ValueError("Invalid, duplicate or mismatched confirmation result")
        observed[result.input_path] = result
    projected = sum(result.saved_bytes for result in pilot.values())
    variance_total = 0.0
    unknown_bytes = unknown_images = 0
    ci_available = True
    for key, members in plan.groups.items():
        remaining = [image for image in members if image.path not in pilot]
        chosen = [image for image in remaining if image.path in selected]
        n, population = len(chosen), len(remaining)
        if population == 0:
            continue
        trials = [observed.get(image.path) for image in chosen]
        if n != plan.quotas[key] or not trials or any(result is None or result.error for result in trials):
            unknown_images += population
            unknown_bytes += sum(image.size_bytes for image in remaining)
            ci_available = False
            continue
        values = [result.saved_bytes for result in trials]
        projected += population * sum(values) / n
        if n < population:
            if n < 2:
                ci_available = False
            else:
                variance_total += population**2 * (1 - n / population) * variance(values) / n
    total = sum(image.size_bytes for members in plan.groups.values() for image in members)
    point = min(total - unknown_bytes, round(projected))
    margin = 1.96 * math.sqrt(variance_total)
    diagnostics = plan._coverage_diagnostics()
    return {
        "scope": "conditional_confirmation",
        "sampling_stage": plan.sampling_stage,
        "population_warning": plan.population_warning,
        "projected_total_saved_bytes": point if not unknown_images else None,
        "projected_covered_saved_bytes": point,
        "unestimated_bytes": unknown_bytes,
        "unestimated_images": unknown_images,
        "approximate_95_percent_interval_bytes": (
            [max(0, round(point - margin)), min(total, round(point + margin))] if ci_available else None
        ),
        "two_stage_adjusted_95_percent_interval_bytes": None,
        "interval_method": "Known pilot totals plus remaining-population stratified finite correction",
        "coverage_gaps": diagnostics["coverage_gaps"],
        "unsampled_formats": diagnostics["unsampled_formats"],
        "unsampled_large_images": diagnostics["unsampled_large_images"],
        "unsampled_tall_webp_images": diagnostics["unsampled_tall_webp_images"],
        "pilot_advisor": None,
        "uncertainty": "Conditional on the measured pilot; confirmation quotas must be fixed before its outcomes "
        "are examined. Normal-approximation interval, not a guarantee; small/skewed samples can understate "
        "uncertainty. No arbitrary outcome-adaptive pooling or repeated-stopping guarantee.",
    }
