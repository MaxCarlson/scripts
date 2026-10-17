"""Seeded gallery-stratified sampling and design-weighted storage projections."""

from __future__ import annotations

from collections import defaultdict
import argparse
from dataclasses import dataclass
import math
import hashlib
import heapq
from pathlib import Path
from statistics import variance
from typing import Mapping, Sequence

from .models import ImageMetadata, ImageResult


def parse_sample(value: str):
    if value == "auto":
        return value
    if value.endswith("%"):
        try:
            pct = float(value[:-1])
            if not (0 < pct <= 100) or not math.isfinite(pct):
                raise ValueError
            return f"{pct:g}%"
        except ValueError:
            raise argparse.ArgumentTypeError("Sample percentage must be greater than 0 and at most 100") from None
    try:
        result = int(value)
        if result < 1:
            raise ValueError
        return result
    except ValueError:
        raise argparse.ArgumentTypeError("Sample must be a positive integer, percentage (e.g. 10%), or auto") from None


def add_analysis_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-U",
        "--inventory-policy",
        choices=("refresh", "trust"),
        default="refresh",
        help="Refresh membership (default) or explicitly trust a completed header snapshot; analysis only.",
    )
    parser.add_argument(
        "-D",
        "--inventory-depth",
        choices=("headers", "files"),
        default="headers",
        help="Inventory depth: verified headers (default) or fast unverified file sizes/extensions; files requires -l.",
    )
    from .preview import add_preview_arguments

    add_preview_arguments(parser)
    parser.add_argument(
        "-k",
        "--cache-policy",
        choices=("use", "refresh", "off"),
        default="use",
        help="Trial cache policy: validated reuse (default), fresh trials, or no disk cache.",
    )
    parser.add_argument(
        "-I",
        "--inventory-file",
        type=Path,
        help="Durable inventory SQLite file outside the input tree (default: per-library user cache).",
    )
    parser.add_argument(
        "-l",
        "--inventory-only",
        nargs="?",
        const="headers",
        default=False,
        choices=("headers", "files"),
        help="Refresh and report image inventory without running encoders (optional depth: headers or files).",
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
    parser.add_argument(
        "-X",
        "--scratch-dir",
        type=Path,
        help="Optional external SSD scratch directory for read-only analysis staging of uncached inputs.",
    )


def validate_analysis_arguments(args: argparse.Namespace) -> None:
    inv_only = getattr(args, "inventory_only", False)
    if inv_only == "files":
        args.inventory_depth = "files"
    if inv_only:
        args.inventory_only = True

    sample = getattr(args, "sample", None)
    if isinstance(sample, str) and sample.endswith("%"):
        if getattr(args, "sample_percent", None) is not None:
            raise ValueError("Choose --sample or --sample-percent, not both")
        try:
            pct = float(sample[:-1])
            if not (0 < pct <= 100) or not math.isfinite(pct):
                raise ValueError
            args.sample_percent = pct
            args.sample = None
        except ValueError:
            raise ValueError("Sample percentage must be greater than 0 and at most 100")

    if getattr(args, "inventory_policy", "refresh") == "trust" and any(
        getattr(args, key, False) for key in ("write", "recover", "inventory_only", "preview_dir")
    ):
        raise ValueError("Trusted snapshots are read-only analysis only; omit writes/recovery/inventory-only/preview")
    scratch_dir = getattr(args, "scratch_dir", None)
    if scratch_dir is not None:
        if any(getattr(args, key, False) for key in ("write", "recover", "inventory_only", "preview_dir")):
            raise ValueError(
                "Scratch staging is read-only analysis only; omit writes, recovery, inventory-only, and preview"
            )
        target = getattr(args, "input", None) or getattr(args, "destination", None)
        if target is not None:
            from .scratch import validate_scratch_dir

            validate_scratch_dir(scratch_dir, target)
    if getattr(args, "inventory_depth", "headers") == "files":
        if not getattr(args, "inventory_only", False):
            raise ValueError("Filesystem-only depth requires --inventory-only; compression requires verified headers")
        if getattr(args, "url", None):
            raise ValueError(
                "Filesystem inventory does not yet support -u filters; target one gallery or use header depth"
            )
    from .preview import validate_preview_arguments

    validate_preview_arguments(args)
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


def _rank_gallery_members(
    members: Sequence[ImageMetadata], root: Path, is_directory: bool, seed: int
) -> list[ImageMetadata]:
    return sorted(
        members,
        key=lambda image: hashlib.sha256(
            f"{seed}\0{image.path.absolute().relative_to(root) if is_directory else image.path.name}".encode()
        ).digest(),
    )


@dataclass
class GallerySample:
    images: list[ImageMetadata]
    groups: dict[str, list[ImageMetadata]]
    quotas: dict[str, int]
    seed: int
    population_warning: str = ""
    sampling_stage: str = "primary"
    pilot_images: tuple[ImageMetadata, ...] = ()
    pilot_observations: tuple[ImageResult, ...] = ()
    allocation_method: str = "balanced"
    profile_identity: str = ""

    def _coverage_diagnostics(self) -> dict:
        formats = defaultdict(lambda: {"images": 0, "bytes": 0, "sample_images": 0})
        chosen = {image.path for image in self.images}
        all_images = [image for members in self.groups.values() for image in members]
        for image in all_images:
            row = formats[image.format.upper()]
            row["images"] += 1
            row["bytes"] += image.size_bytes
            row["sample_images"] += image.path in chosen
        unsampled_formats = sorted(fmt for fmt, row in formats.items() if row["sample_images"] == 0)
        sizes = sorted(image.size_bytes for image in all_images)
        if sizes:
            decile_idx = max(0, min(len(sizes) - 1, math.floor(0.9 * (len(sizes) - 1))))
            large_threshold = sizes[decile_idx]
            large_images = [image for image in all_images if image.size_bytes >= large_threshold]
            sampled_large = sum(image.path in chosen for image in large_images)
            unsampled_large = len(large_images) - sampled_large
        else:
            large_threshold = 0
            sampled_large = 0
            unsampled_large = 0
        tall_images = [image for image in all_images if image.width > 16383 or image.height > 16383]
        sampled_tall = sum(image.path in chosen for image in tall_images)
        unsampled_tall = len(tall_images) - sampled_tall
        singleton_galleries = sum(self.quotas[k] == 1 and len(v) > 1 for k, v in self.groups.items())

        gaps: list[str] = [f"unsampled_format:{fmt}" for fmt in unsampled_formats]
        if unsampled_large > 0 and sampled_large == 0:
            gaps.append("unsampled_top_decile_large_images")
        if unsampled_tall > 0 and sampled_tall == 0:
            gaps.append("unsampled_webp_dimension_limit_images")
        if singleton_galleries > 0:
            gaps.append("singleton_non_census_galleries")

        return {
            "formats": dict(sorted(formats.items())),
            "unsampled_formats": unsampled_formats,
            "large_image_threshold_bytes": large_threshold,
            "sampled_large_images": sampled_large,
            "unsampled_large_images": unsampled_large,
            "sampled_tall_webp_images": sampled_tall,
            "unsampled_tall_webp_images": unsampled_tall,
            "singleton_sample_galleries": singleton_galleries,
            "coverage_minimum_images": len(self.groups),
            "variance_minimum_images": sum(min(2, len(v)) for v in self.groups.values()),
            "coverage_gaps": gaps,
        }

    def summary(self) -> dict:
        diag = self._coverage_diagnostics()
        return {
            "method": "gallery-stratified simple random sampling without replacement",
            "sampling_stage": self.sampling_stage,
            "allocation_method": self.allocation_method,
            "profile_identity": self.profile_identity,
            "population_warning": self.population_warning,
            "allocation": (
                "gallery coverage then input-size variance proxy (0.15 mean floor; heuristic, not precision)"
                if self.allocation_method == "metadata_proxy"
                else "one per gallery (two where budget permits), then equal image-count and byte weighting"
            ),
            "seed": self.seed,
            "sampling_revision": 3 if self.allocation_method == "metadata_proxy" else 2,
            "inventory_images": sum(map(len, self.groups.values())),
            "inventory_bytes": sum(i.size_bytes for g in self.groups.values() for i in g),
            "sample_images": len(self.images),
            "galleries": len(self.groups),
            "sampled_galleries": sum(n > 0 for n in self.quotas.values()),
            "singleton_sample_galleries": diag["singleton_sample_galleries"],
            "coverage_minimum_images": diag["coverage_minimum_images"],
            "variance_minimum_images": diag["variance_minimum_images"],
            "unsampled_formats": diag["unsampled_formats"],
            "large_image_threshold_bytes": diag["large_image_threshold_bytes"],
            "sampled_large_images": diag["sampled_large_images"],
            "unsampled_large_images": diag["unsampled_large_images"],
            "sampled_tall_webp_images": diag["sampled_tall_webp_images"],
            "unsampled_tall_webp_images": diag["unsampled_tall_webp_images"],
            "coverage_gaps": diag["coverage_gaps"],
            "formats": diag["formats"],
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

    def advise_sample_size(
        self,
        results: Sequence[ImageResult],
        *,
        target_margin_percent: float = 2.0,
        target_margin_bytes: int | None = None,
        max_runtime_seconds: float | None = None,
    ) -> dict:
        measured = {r.input_path: r for r in results if r is not None and not r.error}
        chosen = {i.path for i in self.images}
        total_bytes = sum(i.size_bytes for g in self.groups.values() for i in g)
        total_images = sum(map(len, self.groups.values()))
        margin_target = (
            max(1, int(target_margin_bytes))
            if target_margin_bytes is not None
            else max(1, round(total_bytes * target_margin_percent / 100.0))
        )
        valid_results = [r for path, r in measured.items() if path in chosen]
        ratios = [r.saved_bytes / max(1, r.original_bytes) for r in valid_results]
        fallback_ratio_sd = math.sqrt(variance(ratios)) if len(ratios) >= 2 else 0.15
        default_ms = (
            sum(max(0.1, getattr(r, "elapsed_s", 0.025) * 1000.0) for r in valid_results) / len(valid_results)
            if valid_results
            else 25.0
        )

        stratum_var: dict[str, float] = {}
        stratum_ms: dict[str, float] = {}
        singleton_imputed = False
        exact_ci_possible = True
        current_var_total = 0.0

        for key, members in self.groups.items():
            population = len(members)
            trials = [measured.get(i.path) for i in members if i.path in chosen]
            clean_trials = [t for t in trials if t is not None]
            avg_ms = (
                sum(max(0.1, getattr(t, "elapsed_s", 0.025) * 1000.0) for t in clean_trials) / len(clean_trials)
                if clean_trials
                else default_ms
            )
            stratum_ms[key] = max(0.1, avg_ms)
            n = len(clean_trials)
            if n != self.quotas[key] or n == 0:
                exact_ci_possible = False
            if population <= 1:
                stratum_var[key] = 0.0
                continue
            if n >= 2:
                s2 = variance([t.saved_bytes for t in clean_trials])
                stratum_var[key] = s2
                if n < population:
                    current_var_total += population**2 * (1 - n / population) * s2 / n
            else:
                exact_ci_possible = False
                singleton_imputed = True
                mean_size = sum(i.size_bytes for i in members) / population
                stratum_var[key] = max(1.0, (fallback_ratio_sd * mean_size) ** 2)

        current_margin = round(1.96 * math.sqrt(current_var_total)) if exact_ci_possible else None
        precision_met = current_margin is not None and current_margin <= margin_target

        rec_quotas = {
            key: min(len(members), max(self.quotas[key], min(2, len(members)))) for key, members in self.groups.items()
        }

        def _projected_margin(quotas_map: Mapping[str, int]) -> float:
            total_v = 0.0
            for key, members in self.groups.items():
                pop = len(members)
                nh = quotas_map[key]
                if nh < pop and pop > 1:
                    total_v += pop**2 * (1 - nh / pop) * stratum_var[key] / max(1, nh)
            return 1.96 * math.sqrt(total_v)

        additional_ms = sum(max(0, rec_quotas[key] - self.quotas[key]) * stratum_ms[key] for key in self.groups)
        max_ms = max_runtime_seconds * 1000.0 if max_runtime_seconds is not None else None
        budget_capped = False

        while _projected_margin(rec_quotas) > margin_target:
            best_key = None
            best_gain = 0.0
            for key, members in self.groups.items():
                pop = len(members)
                nh = rec_quotas[key]
                if nh >= pop or stratum_var[key] <= 0:
                    continue
                delta_v = (pop**2) * stratum_var[key] * (1.0 / nh - 1.0 / (nh + 1))
                gain_per_ms = delta_v / stratum_ms[key]
                if gain_per_ms > best_gain:
                    best_gain = gain_per_ms
                    best_key = key
            if best_key is None:
                break
            if max_ms is not None and additional_ms + stratum_ms[best_key] > max_ms:
                budget_capped = True
                break
            rec_quotas[best_key] += 1
            additional_ms += stratum_ms[best_key]

        rec_total = sum(rec_quotas.values())
        add_total = max(0, rec_total - len(self.images))
        return {
            "target_margin_bytes": margin_target,
            "target_margin_percent": target_margin_percent,
            "current_margin_bytes": current_margin,
            "projected_margin_bytes": round(_projected_margin(rec_quotas)),
            "precision_met": precision_met,
            "runtime_budget_capped": budget_capped,
            "singleton_variance_imputed": singleton_imputed,
            "coverage_minimum_images": len(self.groups),
            "variance_minimum_images": sum(min(2, len(v)) for v in self.groups.values()),
            "recommended_total_samples": min(total_images, rec_total),
            "recommended_additional_confirmation_samples": add_total,
            "recommended_quotas": rec_quotas,
            "estimated_additional_runtime_seconds": round(additional_ms / 1000.0, 3),
            "adaptive_stopping_note": (
                "Inventory coverage minimum only guarantees one image per gallery, not statistical accuracy. "
                "Because inspecting a pilot interval before choosing whether to stop can understate uncertainty, "
                "evaluate a disjoint confirmation_sample() with measured pilot_results and quotas fixed before "
                "examining confirmation outcomes. Do not pool outcome-adaptive top-up trials using a fixed-design interval."
            ),
        }

    def estimate(self, results: Sequence[ImageResult]) -> dict:
        if self.sampling_stage == "disjoint_confirmation":
            from .confirmation import estimate_confirmation

            return estimate_confirmation(self, results)
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
        std_error = math.sqrt(variance_total)
        margin = 1.96 * std_error
        diag = self._coverage_diagnostics()
        is_full = len(self.images) == sum(map(len, self.groups.values()))
        return {
            "scope": "full" if is_full else "gallery_random_sample",
            "sampling_stage": self.sampling_stage,
            "population_warning": self.population_warning,
            "projected_total_saved_bytes": point if not unknown_bytes else None,
            "projected_covered_saved_bytes": point,
            "unestimated_bytes": unknown_bytes,
            "unestimated_images": unknown_images,
            "approximate_95_percent_interval_bytes": (
                [max(0, round(point - margin)), min(total, round(point + margin))] if ci_available else None
            ),
            "two_stage_adjusted_95_percent_interval_bytes": None,
            "coverage_gaps": diag["coverage_gaps"],
            "unsampled_formats": diag["unsampled_formats"],
            "unsampled_large_images": diag["unsampled_large_images"],
            "unsampled_tall_webp_images": diag["unsampled_tall_webp_images"],
            "pilot_advisor": (
                None if is_full or self.allocation_method == "metadata_proxy" else self.advise_sample_size(results)
            ),
            "uncertainty": "Design-weighted estimate; normal-approximation interval, not a guarantee. "
            "Small or highly skewed samples can understate uncertainty. "
            "Interval unavailable when a non-census gallery has only one sample or a trial fails. "
            "Rare image types may be missed; increase the sample or repeat with a different seed.",
        }


def _allocate_quotas(
    groups: Mapping[str, Sequence[ImageMetadata]], capacities: Mapping[str, int], target: int, proxy_weights=None
) -> dict[str, int]:
    active_keys = [key for key in groups if capacities[key] > 0]
    quotas = {key: 0 for key in groups}
    all_images = [i for g in groups.values() for i in g]
    count = max(1, len(all_images))
    total_bytes = max(1, sum(i.size_bytes for i in all_images))
    weights = {k: 0.5 * len(v) / count + 0.5 * sum(i.size_bytes for i in v) / total_bytes for k, v in groups.items()}
    if proxy_weights is not None:
        weights = proxy_weights

    if target < len(active_keys):
        selected_keys = sorted(active_keys, key=lambda key: (-weights[key], key))[:target]
        for key in selected_keys:
            quotas[key] = 1
        return quotas

    for key in active_keys:
        quotas[key] = 1
    remaining = target - sum(quotas.values())
    second = sorted((key for key in active_keys if capacities[key] > 1), key=lambda key: (-weights[key], key))
    for key in second[:remaining]:
        quotas[key] += 1
        remaining -= 1
    heap = [(-weights[key], key) for key in active_keys if quotas[key] < capacities[key]]
    heapq.heapify(heap)
    baseline = dict(quotas)
    while remaining and heap:
        _, key = heapq.heappop(heap)
        quotas[key] += 1
        remaining -= 1
        if quotas[key] < capacities[key]:
            heapq.heappush(heap, (-weights[key] / (quotas[key] - baseline[key] + 1), key))
    return quotas


def gallery_sample(
    images: Sequence[ImageMetadata],
    root: Path,
    *,
    sample_size: int | str | None = None,
    percent: float | None = None,
    seed: int = 0,
    gallery_keys: Mapping[Path, str] | None = None,
    profile=None,
) -> GallerySample:
    """Allocate deterministic quotas, then draw uniform random samples within galleries."""
    if sample_size is not None and sample_size != "auto" and sample_size < 1:
        raise ValueError("Sample size must be positive")
    if percent is not None and (not math.isfinite(percent) or not 0 < percent <= 100):
        raise ValueError("Sample percentage must be greater than 0 and at most 100")
    if sample_size is not None and percent is not None:
        raise ValueError("Choose sample size or percentage, not both")
    if sample_size == "auto" and profile is None:
        raise ValueError("Automatic sampling needs a matching completed header profile; use -U refresh")
    if profile is not None:
        profile.validate(images, root, gallery_keys)
        if sample_size == "auto":
            sample_size = profile.data["starter_samples"]
    groups = defaultdict(list)
    root = root.resolve()
    is_directory = root.is_dir()
    for image in images:
        # Scanner/snapshot paths are absolute. Resolving all population members
        # can reopen them on Windows, defeating selected-only snapshot validation.
        if ".." in image.path.parts:
            raise ValueError("Sampling requires canonical image paths without '..'")
        relative = image.path.absolute().relative_to(root) if is_directory else Path(image.path.name)
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
    capacities = {key: len(members) for key, members in groups.items()}
    weights = (
        {key: row["proxy_weight"] for key, row in profile.data["galleries"].items()} if profile is not None else None
    )
    quotas = _allocate_quotas(groups, capacities, target, weights)
    selected = []
    for key, members in groups.items():
        # Seeded file priorities give a stable pseudorandom permutation; selecting
        # a longer prefix retains all earlier samples for an unchanged population.
        ranked = _rank_gallery_members(members, root, is_directory, seed)
        selected.extend(ranked[: quotas[key]])
    return GallerySample(
        sorted(selected, key=lambda i: str(i.path).casefold()),
        groups,
        quotas,
        seed,
        allocation_method="metadata_proxy" if profile else "balanced",
        profile_identity=profile.identity if profile else "",
    )


def confirmation_sample(
    pilot: GallerySample,
    root: Path,
    *,
    sample_size: int | None = None,
    target_quotas: Mapping[str, int] | None = None,
    pilot_results: Sequence[ImageResult] | None = None,
) -> GallerySample:
    """Draw a disjoint confirmation sample from the remaining unselected items per gallery."""
    from .confirmation import validate_pilot_results

    if pilot.sampling_stage != "primary":
        raise ValueError("Confirmation requires a primary measured pilot, not nested confirmation")
    validate_pilot_results(pilot.images, pilot_results)
    root = root.resolve()
    is_directory = root.is_dir()
    remaining_by_gallery: dict[str, list[ImageMetadata]] = {}
    for key, members in pilot.groups.items():
        ranked = _rank_gallery_members(members, root, is_directory, pilot.seed)
        selected_pilot = {image.path for image in pilot.images}
        remaining_by_gallery[key] = [image for image in ranked if image.path not in selected_pilot]
    capacities = {key: len(rem) for key, rem in remaining_by_gallery.items()}
    total_remaining = sum(capacities.values())
    if total_remaining == 0:
        raise ValueError("No unselected images remain for a disjoint confirmation sample")
    if target_quotas is not None:
        quotas = {
            key: min(
                capacities[key], max(1 if capacities[key] > 0 else 0, target_quotas.get(key, 0) - pilot.quotas[key])
            )
            for key in pilot.groups
        }
    else:
        default_target = sum(min(2, cap) for cap in capacities.values())
        target = min(total_remaining, sample_size if sample_size is not None else default_target)
        quotas = _allocate_quotas(pilot.groups, capacities, target)
    selected = []
    for key, rem in remaining_by_gallery.items():
        selected.extend(rem[: quotas[key]])
    return GallerySample(
        sorted(selected, key=lambda i: str(i.path).casefold()),
        pilot.groups,
        quotas,
        pilot.seed,
        population_warning=pilot.population_warning,
        sampling_stage="disjoint_confirmation",
        pilot_images=tuple(pilot.images),
        pilot_observations=tuple(pilot_results),
    )


def print_sampling(plan: GallerySample) -> None:
    report = plan.summary()
    print(
        f"Sampling: {report['sample_images']}/{report['inventory_images']} images; "
        f"{report['sampled_galleries']}/{report['galleries']} galleries; seed {plan.seed}"
    )
    print(
        f"Allocation: per-gallery coverage (minimum {report['coverage_minimum_images']} images; "
        f"{report['variance_minimum_images']} for within-gallery variance). {report['allocation']}."
    )
    if plan.allocation_method == "metadata_proxy":
        print(
            "Design: metadata_proxy revision3; input-size proxy with0.15 mean floor. Starter coverage is not a statistical minimum or accuracy guarantee."
        )
    for fmt, row in report["formats"].items():
        print(f"  {fmt}: {row['images']} images, {row['bytes']} bytes; {row['sample_images']} sampled")
    if report["unsampled_formats"]:
        print(f"Coverage note: rare formats not in sample: {', '.join(report['unsampled_formats'])}.")
    if report["unsampled_large_images"] and not report["sampled_large_images"]:
        print(
            f"Coverage note: {report['unsampled_large_images']} top-decile large images "
            f"(>= {report['large_image_threshold_bytes']:,} bytes) were not sampled."
        )
    if report["unsampled_tall_webp_images"] and not report["sampled_tall_webp_images"]:
        print(
            f"Coverage note: {report['unsampled_tall_webp_images']} images exceeding WebP's 16,383px dimension "
            "limit were not sampled."
        )
    if report["singleton_sample_galleries"]:
        print(
            f"Warning: {report['singleton_sample_galleries']} non-census galleries have only one sample; "
            "uncertainty cannot be calculated. Increase -s/-P."
        )
