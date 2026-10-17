"""Seeded gallery-stratified sampling and design-weighted storage projections."""

from __future__ import annotations

from collections import defaultdict
import argparse
from dataclasses import dataclass
import math
from pathlib import Path
import random
from statistics import variance
from typing import Mapping, Sequence

from .models import ImageMetadata, ImageResult


def add_analysis_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-I",
        "--inventory-file",
        type=Path,
        help="Durable inventory SQLite file outside the input tree (default: per-library user cache).",
    )
    parser.add_argument(
        "-l",
        "--inventory-only",
        action="store_true",
        help="Refresh and report image inventory without running encoders.",
    )
    parser.add_argument(
        "-b",
        "--compare-both",
        action="store_true",
        help="Compare full lossless and lossy strategy sets together; implies -c. Lossy uses -q.",
    )
    parser.add_argument(
        "-P",
        "--sample-percent",
        type=float,
        help="Randomly sample this percentage of eligible images, covering every gallery (0..100, exclusive of 0).",
    )
    parser.add_argument(
        "-z", "--sample-seed", type=int, default=0, help="Reproducible gallery sampling seed (default: 0)."
    )


def validate_analysis_arguments(args: argparse.Namespace) -> None:
    if getattr(args, "inventory_only", False) and (
        args.write
        or args.compare
        or getattr(args, "compare_both", False)
        or getattr(args, "recover", False)
        or args.sample is not None
        or getattr(args, "sample_percent", None) is not None
    ):
        raise ValueError("Inventory-only cannot be combined with writes, comparison, recovery or sampling")
    if getattr(args, "compare_both", False):
        args.compare = True
    percent = getattr(args, "sample_percent", None)
    if percent is not None and (not math.isfinite(percent) or not 0 < percent <= 100):
        raise ValueError("Sample percentage must be greater than 0 and at most 100")
    if percent is not None and args.sample is not None:
        raise ValueError("Choose --sample or --sample-percent, not both")
    if getattr(args, "recover", False) and (percent is not None or args.compare):
        raise ValueError("Recovery cannot be combined with sampling or comparison")
    if args.write and (args.sample is not None or percent is not None or args.compare):
        raise ValueError("Sampling and comparison are analysis-only; omit --write")


@dataclass
class GallerySample:
    images: list[ImageMetadata]
    groups: dict[str, list[ImageMetadata]]
    quotas: dict[str, int]
    seed: int

    def summary(self) -> dict:
        formats = defaultdict(lambda: {"images": 0, "bytes": 0, "sample_images": 0})
        chosen = {image.path for image in self.images}
        for members in self.groups.values():
            for image in members:
                row = formats[image.format.upper()]
                row["images"] += 1
                row["bytes"] += image.size_bytes
                row["sample_images"] += image.path in chosen
        return {
            "method": "gallery-stratified simple random sampling without replacement",
            "allocation": "one per gallery (two where budget permits), then equal image-count and byte weighting",
            "seed": self.seed,
            "inventory_images": sum(map(len, self.groups.values())),
            "inventory_bytes": sum(i.size_bytes for g in self.groups.values() for i in g),
            "sample_images": len(self.images),
            "galleries": len(self.groups),
            "sampled_galleries": sum(n > 0 for n in self.quotas.values()),
            "singleton_sample_galleries": sum(self.quotas[k] == 1 and len(v) > 1 for k, v in self.groups.items()),
            "formats": dict(sorted(formats.items())),
            "gallery_inventory": [
                {
                    "gallery": key,
                    "images": len(members),
                    "bytes": sum(i.size_bytes for i in members),
                    "sample_images": self.quotas[key],
                }
                for key, members in self.groups.items()
            ],
        }

    def estimate(self, results: Sequence[ImageResult]) -> dict:
        measured = {r.input_path: r for r in results}
        chosen = {i.path for i in self.images}
        projected = 0.0
        variance_total = 0.0
        unknown_bytes = 0
        unknown_images = 0
        ci_available = True
        for key, members in self.groups.items():
            trials = [measured.get(i.path) for i in members if i.path in chosen]
            if len(trials) != self.quotas[key] or not trials or any(r is None or r.error for r in trials):
                unknown_bytes += sum(i.size_bytes for i in members)
                unknown_images += len(members)
                ci_available = False
                continue
            values = [r.saved_bytes for r in trials]
            n, population = len(values), len(members)
            projected += population * sum(values) / n
            if n < population:
                if n < 2:
                    ci_available = False
                else:
                    variance_total += population**2 * (1 - n / population) * variance(values) / n
        total = sum(i.size_bytes for g in self.groups.values() for i in g)
        point = min(total - unknown_bytes, round(projected))
        margin = 1.96 * math.sqrt(variance_total)
        return {
            "scope": "full" if len(self.images) == sum(map(len, self.groups.values())) else "gallery_random_sample",
            "projected_total_saved_bytes": point if not unknown_bytes else None,
            "projected_covered_saved_bytes": point,
            "unestimated_bytes": unknown_bytes,
            "unestimated_images": unknown_images,
            "approximate_95_percent_interval_bytes": (
                [max(0, round(point - margin)), min(total, round(point + margin))] if ci_available else None
            ),
            "uncertainty": "Design-weighted estimate; normal-approximation interval, not a guarantee. "
            "Small or highly skewed samples can understate uncertainty. "
            "Interval unavailable when a non-census gallery has only one sample or a trial fails. "
            "Rare image types may be missed; increase the sample or repeat with a different seed.",
        }


def gallery_sample(
    images: Sequence[ImageMetadata],
    root: Path,
    *,
    sample_size: int | None = None,
    percent: float | None = None,
    seed: int = 0,
    gallery_keys: Mapping[Path, str] | None = None,
) -> GallerySample:
    """Allocate deterministic quotas, then draw uniform random samples within galleries."""
    if sample_size is not None and sample_size < 1:
        raise ValueError("Sample size must be positive")
    if percent is not None and (not math.isfinite(percent) or not 0 < percent <= 100):
        raise ValueError("Sample percentage must be greater than 0 and at most 100")
    if sample_size is not None and percent is not None:
        raise ValueError("Choose sample size or percentage, not both")
    groups = defaultdict(list)
    root = root.resolve()
    for image in images:
        relative = image.path.resolve().relative_to(root) if root.is_dir() else Path(image.path.name)
        key = (
            gallery_keys[image.path]
            if gallery_keys is not None
            else (str(root / relative.parts[0]) if len(relative.parts) > 1 else str(root))
        )
        groups[str(key)].append(image)
    groups = {k: sorted(v, key=lambda i: str(i.path).casefold()) for k, v in sorted(groups.items())}
    count = len(images)
    target = (
        min(count, sample_size)
        if sample_size is not None
        else (min(count, max(len(groups), math.ceil(count * percent / 100))) if percent is not None else count)
    )
    if target < len(groups):
        raise ValueError(
            f"Sample {target} cannot cover {len(groups)} galleries; use -s {len(groups)} or more, "
            "or -P for a percentage with automatic per-gallery coverage"
        )
    minimum = {k: min(2, len(v)) for k, v in groups.items()}
    quotas = minimum if target >= sum(minimum.values()) else {k: 1 for k in groups}
    total_bytes = sum(i.size_bytes for i in images)
    weights = {
        k: 0.5 * len(v) / count + 0.5 * sum(i.size_bytes for i in v) / max(1, total_bytes) for k, v in groups.items()
    }
    # Capped proportional allocation. Recompute after a gallery fills its quota.
    remaining = target - sum(quotas.values())
    while remaining:
        eligible = [k for k in groups if quotas[k] < len(groups[k])]
        weight_sum = sum(weights[k] for k in eligible)
        shares = {k: remaining * weights[k] / weight_sum for k in eligible}
        allocated = 0
        for key in eligible:
            extra = min(len(groups[key]) - quotas[key], int(shares[key]))
            quotas[key] += extra
            allocated += extra
        remaining -= allocated
        if remaining and not allocated:
            for key in sorted(eligible, key=lambda k: (-shares[k], k))[:remaining]:
                quotas[key] += 1
                remaining -= 1
    rng = random.Random(seed)
    selected = [i for k, members in groups.items() for i in rng.sample(members, quotas[k])]
    return GallerySample(sorted(selected, key=lambda i: str(i.path).casefold()), groups, quotas, seed)


def print_sampling(plan: GallerySample) -> None:
    report = plan.summary()
    print(
        f"Sampling: {report['sample_images']}/{report['inventory_images']} images; "
        f"{report['sampled_galleries']}/{report['galleries']} galleries; seed {plan.seed}"
    )
    print("Allocation: per-gallery coverage, then equal weighting of image-count and byte shares.")
    for fmt, row in report["formats"].items():
        print(f"  {fmt}: {row['images']} images, {row['bytes']} bytes; {row['sample_images']} sampled")
    if report["singleton_sample_galleries"]:
        print(
            f"Warning: {report['singleton_sample_galleries']} non-census galleries have only one sample; "
            "uncertainty cannot be calculated. Increase -s/-P."
        )
