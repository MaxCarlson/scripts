"""Explicitly scoped, stratified savings projections, never invented certainty."""

from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from .models import ImageMetadata, ImageResult
from .scanner import sample_stratum


def estimate_savings(images: Sequence[ImageMetadata], results: Sequence[ImageResult]) -> dict:
    population: dict[tuple, list[ImageMetadata]] = defaultdict(list)
    measured: dict[tuple, list[ImageResult]] = defaultdict(list)
    identities = {item.path.resolve(): item for item in images}
    for image in images:
        population[sample_stratum(image)].append(image)
    for result in results:
        image = identities.get(result.input_path.resolve())
        if image:
            measured[sample_stratum(image)].append(result)
    projected = 0
    unestimated_bytes = 0
    unestimated_images = 0
    for key, members in population.items():
        trials = measured[key]
        byte_total = sum(item.size_bytes for item in members)
        if not trials or any(trial.error for trial in trials):
            unestimated_bytes += byte_total
            unestimated_images += len(members)
            continue
        measured_bytes = sum(trial.original_bytes for trial in trials)
        ratio = sum(trial.saved_bytes for trial in trials) / max(1, measured_bytes)
        projected += round(byte_total * ratio)
    return {
        "scope": "full" if len(results) == len(images) else "stratified_sample",
        "inventory_images": len(images),
        "inventory_bytes": sum(item.size_bytes for item in images),
        "measured_images": len(results),
        "measured_bytes": sum(item.original_bytes for item in results),
        "measured_saved_bytes": sum(item.saved_bytes for item in results),
        "projected_covered_saved_bytes": projected,
        "unestimated_images": unestimated_images,
        "unestimated_bytes": unestimated_bytes,
        "projected_total_saved_bytes": projected if not unestimated_images else None,
        "uncertainty": "Measured outputs only"
        if len(results) == len(images)
        else "Deterministic stratified projection; not a statistical confidence interval or visual-quality guarantee",
    }
