"""Explicit model-based byte ratios, distinct from design-based sampling estimates."""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from typing import Sequence

from .models import ImageMetadata, ImageResult


def extrapolate_target(
    population: Sequence[ImageMetadata],
    selected: Sequence[ImageMetadata],
    results: Sequence[ImageResult],
    *,
    complete: bool,
) -> dict:
    inventory = {i.path: i for i in population}
    chosen = {i.path: i for i in selected}
    observed = {r.input_path: r for r in results}
    if (
        len(inventory) != len(population)
        or len(chosen) != len(selected)
        or len(observed) != len(results)
        or not chosen.keys() <= inventory.keys()
        or not observed.keys() <= chosen.keys()
    ):
        raise ValueError("Extrapolation needs unique inventory/selection/results with matching source paths")
    if any(i != inventory[i.path] for i in selected):
        raise ValueError("Selection metadata differs from inventory")
    formats = defaultdict(
        lambda: dict(
            images=0, bytes=0, sample_images=0, sample_bytes=0, observed_images=0, observed_bytes=0, saved_bytes=0
        )
    )
    for image in population:
        if image.size_bytes < 0:
            raise ValueError("Inventory bytes cannot be negative")
        fmt = image.format.upper()
        fmt = "JPEG" if fmt == "JPG" else fmt
        row = formats[fmt]
        row["images"] += 1
        row["bytes"] += image.size_bytes
        if image.path in chosen:
            row["sample_images"] += 1
            row["sample_bytes"] += image.size_bytes
        result = observed.get(image.path)
        if result is not None:
            if result.compressed_bytes < 0 or (not result.error and result.original_bytes != image.size_bytes):
                raise ValueError("Trial byte counts do not match source metadata")
            row["observed_images"] += 1
            row["observed_bytes"] += image.size_bytes
            row["saved_bytes"] += 0 if result.error else image.size_bytes - result.compressed_bytes
    total = sum(i.size_bytes for i in population)
    sample_total = sum(i.size_bytes for i in selected)
    observed_bytes = sum(f["observed_bytes"] for f in formats.values())
    observed_saved = sum(f["saved_bytes"] for f in formats.values())
    overall = Fraction(observed_saved, observed_bytes) if observed_bytes else None
    census = complete and bool(population) and observed.keys() == inventory.keys()
    partial = not complete or len(observed) != len(chosen)
    warnings = []
    fallback_bytes = 0
    projection = Fraction(0)
    for row in formats.values():
        ratio = Fraction(row["saved_bytes"], row["observed_bytes"]) if row["observed_bytes"] else overall
        row["basis"] = "format-specific sample" if row["observed_bytes"] else "overall-ratio fallback"
        row["ratio"] = float(ratio) if ratio is not None else None
        row["count_coverage_percent"] = row["sample_images"] / row["images"] * 100 if row["images"] else 0
        row["byte_coverage_percent"] = row["sample_bytes"] / row["bytes"] * 100 if row["bytes"] else 0
        if not row["observed_bytes"]:
            fallback_bytes += row["bytes"]
        if ratio is not None:
            projection += row["bytes"] * ratio
    failures = sum(bool(r.error) for r in results)
    successful = len(results) - failures
    if not census:
        warnings.append("Model-based extrapolation, not guaranteed savings or statistical confidence bounds.")
    if fallback_bytes:
        warnings.append("Unsampled formats use the overall observed byte-savings ratio.")
    if results and not successful:
        warnings.append("no successful encodes; originals retained")
    if overall is None:
        warnings.append("No positive-byte observations; a savings ratio cannot be calculated.")
    saved = round(projection) if overall is not None else None
    return dict(
        schema=1,
        method="format_ratio_v1",
        status="partial" if partial else "calculated" if census else "estimated",
        target_images=len(population),
        target_bytes=total,
        sample_images=len(selected),
        sample_bytes=sample_total,
        observed_images=len(results),
        observed_bytes=observed_bytes,
        saved_bytes=saved,
        retained_bytes=total - saved if saved is not None else None,
        reduction_percent=saved / total * 100 if saved is not None and total else None,
        fallback_bytes=fallback_bytes,
        fallback_percent=fallback_bytes / total * 100 if total else 0,
        successful_count=successful,
        failed_count=failures,
        formats=dict(sorted(formats.items())),
        warnings=warnings,
    )
