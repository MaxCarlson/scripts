"""Shared, operation-scoped compression CLI and typed argument normalization."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
import math
from pathlib import Path
import re

from .estimation_models import RecipeSpec

FORMATS = ("auto", "webp", "jpeg", "avif", "png", "keep")
ENCODERS = ("auto", "pillow-jpeg", "pillow-webp", "pillow-png", "pillow-avif", "cli-jpegtran")
OPERATIONS = ("inventory", "plan", "estimate", "analyze", "compare", "preview", "apply", "recover")
_WORKSPACE_PREVIEW = Path("__workspace_preview__")


def parse_quality(value: str) -> int:
    """Parse an integer quality or exact decimal fraction without float rounding."""
    try:
        quality = Decimal(value)
        if "." in value and Decimal(0) < quality <= Decimal(1):
            quality *= 100
        if not quality.is_finite() or quality != quality.to_integral_value() or not 1 <= quality <= 100:
            raise ValueError
        return int(quality)
    except (InvalidOperation, ValueError):
        raise argparse.ArgumentTypeError("Use quality 1..100 or an exact fraction such as 0.85") from None


def parse_duration(value: str) -> float:
    """Parse a positive finite seconds/minutes/hours duration."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([smh]?)\s*", value, flags=re.IGNORECASE)
    if not match:
        raise argparse.ArgumentTypeError("Use a positive duration such as 30s, 5m, or 1.5h")
    number = Decimal(match.group(1))
    if not number.is_finite() or number <= 0:
        raise argparse.ArgumentTypeError("Duration must be positive and finite")
    scale = {"": 1, "s": 1, "m": 60, "h": 3600}[match.group(2).lower()]
    seconds = float(number * scale)
    if not math.isfinite(seconds):
        raise argparse.ArgumentTypeError("Duration must be finite")
    return seconds


@dataclass(frozen=True, slots=True)
class CompressionOptions:
    operation: str
    owner: str
    target: Path
    filters: tuple[str, ...]
    recipes: tuple[RecipeSpec, ...]
    inventory_depth: str
    inventory_policy: str
    sample: int | str | None
    seed: int
    max_images: int | None
    max_trials: int | None
    max_time_seconds: float | None
    accuracy_pp: float | None
    plan_id: str | None
    plan_recipes_explicit: bool
    plan_seed_explicit: bool
    plan_budget_explicit: bool
    threads: int
    memory_budget: int | str | None
    cache_policy: str
    cache_file: Path | None
    scratch_dir: Path | None
    output: Path | None
    preview_count: int
    write: bool
    allow_lossy: bool
    allow_larger: bool
    confirmation: str | None
    json: bool
    no_ui: bool
    verbose: int

    def legacy_namespace(self, parsed: argparse.Namespace) -> argparse.Namespace:
        """Adapt normalized values to the existing engine boundary during CLI migration."""
        values = vars(parsed).copy()
        values["input"] = self.target
        values["inventory_file"] = getattr(parsed, "workspace", None)
        values["inventory_only"] = self.operation == "inventory"
        values["recover"] = self.operation == "recover"
        values["compare"] = self.operation == "compare"
        values["compare_both"] = self.operation == "compare" and getattr(parsed, "mode", None) == "both"
        values["preview_dir"] = (
            (self.output if self.output is not None else _WORKSPACE_PREVIEW) if self.operation == "preview" else None
        )
        values["preview_count"] = self.preview_count if self.operation == "preview" else None
        preview_qualities = [item.quality for item in self.recipes if item.quality is not None]
        values["preview_qualities"] = preview_qualities or None if self.operation in ("preview", "compare") else None
        recipe = self.recipes[0] if self.recipes else None
        values["format"] = recipe.format if recipe else "auto"
        values["preview_formats"] = (
            tuple(dict.fromkeys(item.format for item in self.recipes)) if self.operation == "preview" else ()
        )
        values["mode"] = recipe.mode if recipe else "lossless"
        values["quality"] = recipe.quality if recipe and recipe.quality is not None else 80
        values["perceptual_target"] = recipe.perceptual_target if recipe else 0.990
        values["algorithm"] = recipe.encoder if recipe else "auto"
        values["effort"] = recipe.effort if recipe else 6
        values["inventory_depth"] = self.inventory_depth
        values["inventory_policy"] = self.inventory_policy
        values["sample_seed"] = self.seed
        values["sample_percent"] = None
        if isinstance(self.sample, str) and self.sample.endswith("%"):
            values["sample"] = None
            values["sample_percent"] = float(self.sample[:-1])
        else:
            values["sample"] = None if self.sample == "all" else self.sample
        values["threads"] = self.threads
        values["memory_budget_mib"] = self.memory_budget if self.memory_budget is not None else 512
        values["cache_policy"] = self.cache_policy
        values["cache_file"] = self.cache_file
        values["scratch_dir"] = self.scratch_dir
        values["write"] = self.write
        values["allow_lossy"] = self.allow_lossy
        values["allow_larger"] = self.allow_larger
        values["confirm_recovery"] = self.confirmation
        values["json"] = self.json
        values["no_ui"] = self.no_ui
        values["verbose"] = self.verbose
        values["output_dir"] = None
        values["_compression_options"] = self
        return argparse.Namespace(**values)


def _target(parser: argparse.ArgumentParser, owner: str) -> None:
    if owner == "mangadl":
        parser.add_argument(
            "-d", "--destination", type=Path, required=True, help="Destination library root or gallery."
        )
    else:
        parser.add_argument("-i", "--input", type=Path, required=True, help="Input image file or directory.")


def _common(parser: argparse.ArgumentParser, owner: str, *, workspace: bool = True, filters: bool = True) -> None:
    _target(parser, owner)
    if workspace:
        parser.add_argument("-I", "--workspace", type=Path, help="Parent directory for the target workspace.")
    if filters and owner == "mangadl":
        parser.add_argument(
            "-u", "--url", action="append", default=[], help="Select an exact source URL or folder; repeatable."
        )
    parser.add_argument("-J", "--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("-N", "--no-ui", action="store_true", help="Disable live terminal progress.")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase diagnostic output.")


def _recipe_options(
    parser: argparse.ArgumentParser,
    *,
    formats_default=None,
    formats_required=False,
    all_formats=False,
    mode_default="lossless",
    mode_choices=None,
    quality_default=None,
    quality_action="extend",
    encoder_default="auto",
    effort_default=6,
    perceptual_default=0.990,
) -> None:
    parser.add_argument(
        "-f",
        "--format",
        nargs="+",
        choices=(*FORMATS, "all") if all_formats else FORMATS,
        default=formats_default,
        required=formats_required,
        help=(
            "Target formats; all includes AUTO, WebP, JPEG, AVIF and PNG in supported modes."
            if all_formats
            else "Target image format(s)."
        ),
    )
    parser.add_argument(
        "-m", "--mode", choices=mode_choices or ("lossless", "lossy", "perceptual"), default=mode_default
    )
    parser.add_argument(
        "-q",
        "--quality",
        type=parse_quality,
        action=quality_action,
        nargs="+",
        default=quality_default,
        help="Quality 1..100 or exact fraction such as 0.85; repeat for multiple qualities.",
    )
    parser.add_argument("-p", "--perceptual-target", type=float, default=perceptual_default)
    parser.add_argument("-A", "--encoder", choices=ENCODERS, default=encoder_default)
    parser.add_argument("-e", "--effort", type=int, choices=range(7), default=effort_default)


def build_operation_parsers(parent: argparse.ArgumentParser, *, owner: str) -> None:
    """Attach the canonical operation tree to a standalone or MangaDL parser."""
    if owner not in ("compresser", "mangadl"):
        raise ValueError("owner must be 'compresser' or 'mangadl'")
    parent.set_defaults(_compression_owner=owner)
    parent.description = "Inventory, estimate, analyze, compare, preview, apply, or recover compression work."
    parent.epilog = "Use an operation subcommand; bare command prints help and performs no scan."
    operations = parent.add_subparsers(dest="operation", metavar="OPERATION")
    operations.add_parser(
        "inventory",
        help="Refresh a descriptive image inventory.",
        description="Refresh and report an image inventory; does not encode images.",
    )
    # Rebuild inventory parser with its own option group rather than sharing a flat argument surface.
    inventory = operations.choices["inventory"]
    _common(inventory, owner)
    inventory.add_argument("-D", "--depth", dest="inventory_depth", choices=("files", "headers"), default="headers")
    inventory.add_argument("-t", "--threads", type=int, default=4)

    plan = operations.add_parser("plan", help="Create or inspect a bounded estimation plan.")
    _common(plan, owner)
    _recipe_options(
        plan,
        all_formats=True,
        mode_choices=("lossless", "lossy", "perceptual", "both"),
        formats_default=None,
        mode_default=None,
        encoder_default=None,
        effort_default=None,
        perceptual_default=None,
    )
    plan.add_argument("-z", "--seed", type=int)
    plan.add_argument("-s", "--max-images", type=_positive_int)
    plan.add_argument("-T", "--max-trials", type=_positive_int)
    plan.add_argument("-M", "--max-time", type=parse_duration)
    plan.add_argument("-a", "--accuracy-pp", type=_positive_decimal)
    plan.add_argument("-F", "--allow-larger", action="store_true")
    plan.add_argument("-r", "--plan-id")

    estimate = operations.add_parser("estimate", help="Execute or resume a bounded estimation plan.")
    _common(estimate, owner)
    _recipe_options(
        estimate,
        all_formats=True,
        mode_choices=("lossless", "lossy", "perceptual", "both"),
        formats_default=None,
        mode_default=None,
        encoder_default=None,
        effort_default=None,
        perceptual_default=None,
    )
    estimate.add_argument("-z", "--seed", type=int, default=None)
    estimate.add_argument("-s", "--max-images", type=_positive_int)
    estimate.add_argument("-T", "--max-trials", type=_positive_int)
    estimate.add_argument("-M", "--max-time", type=parse_duration)
    estimate.add_argument("-a", "--accuracy-pp", type=_positive_decimal)
    estimate.add_argument("-F", "--allow-larger", action="store_true")
    estimate.add_argument("-r", "--plan-id")
    _measurement_options(estimate, scratch=True)

    analyze = operations.add_parser("analyze", help="Measure one exact recipe.")
    _common(analyze, owner)
    _recipe_options(analyze, formats_default=["auto"])
    analyze.add_argument("-s", "--sample", type=_sample_value, default="all")
    analyze.add_argument("-z", "--seed", type=int, default=0)
    analyze.add_argument("-F", "--allow-larger", action="store_true")
    analyze.add_argument("-U", "--inventory-policy", choices=("refresh", "snapshot"), default="refresh")
    _measurement_options(analyze, scratch=True)

    compare = operations.add_parser("compare", help="Benchmark an explicit set of recipes.")
    _common(compare, owner)
    _recipe_options(
        compare,
        formats_required=True,
        all_formats=True,
        mode_default="both",
        mode_choices=("lossless", "lossy", "perceptual", "both"),
    )
    compare.add_argument("-s", "--sample", type=_sample_value, default="all")
    compare.add_argument("-z", "--seed", type=int, default=0)
    compare.add_argument("-F", "--allow-larger", action="store_true")
    compare.add_argument("-U", "--inventory-policy", choices=("refresh", "snapshot"), default="refresh")
    _measurement_options(compare, scratch=True)

    preview = operations.add_parser("preview", help="Write external full-resolution preview copies.")
    _common(preview, owner)
    preview.add_argument("-f", "--format", nargs="+", choices=FORMATS, default=["webp"])
    preview.add_argument("-q", "--quality", type=parse_quality, action="extend", nargs="+")
    preview.add_argument("-A", "--encoder", choices=ENCODERS, default="auto")
    preview.add_argument("-e", "--effort", type=int, choices=range(7), default=6)
    preview.add_argument("-n", "--count", type=_positive_int, default=3)
    preview.add_argument("-O", "--output", type=Path, nargs="?", const=_WORKSPACE_PREVIEW)
    preview.add_argument("-U", "--inventory-policy", choices=("refresh", "snapshot"), default="refresh")
    _measurement_options(preview)

    apply = operations.add_parser("apply", help="Apply one exact recipe to source images.")
    _common(apply, owner)
    _recipe_options(apply, formats_default=["auto"])
    apply.add_argument("-w", "--write", action="store_true", help="Required to mutate source images.")
    apply.add_argument("-L", "--allow-lossy", action="store_true", help="Required for lossy or perceptual writes.")
    apply.add_argument("-F", "--allow-larger", action="store_true")
    apply.add_argument("-U", "--inventory-policy", choices=("refresh", "snapshot"), default="refresh")
    _measurement_options(apply)

    recover = operations.add_parser("recover", help="Preview or apply one exact transaction recovery.")
    _common(recover, owner, workspace=False, filters=False)
    recover.add_argument("-w", "--write", action="store_true", help="Apply the previewed recovery.")
    recover.add_argument(
        "-C", "--confirm", dest="confirm_recovery", help="Exact fresh recovery token required with --write."
    )


def _measurement_options(parser: argparse.ArgumentParser, *, scratch: bool = False) -> None:
    parser.add_argument("-t", "--threads", type=_positive_int, default=4)
    from .memory_policy import parse_memory_budget

    parser.add_argument("-B", "--memory-budget", dest="memory_budget_mib", type=parse_memory_budget, default=512)
    parser.add_argument("-k", "--cache", dest="cache_policy", choices=("use", "refresh", "off"), default="use")
    parser.add_argument("-K", "--cache-file", type=Path)
    if scratch:
        parser.add_argument("-X", "--scratch-dir", type=Path)


def _positive_int(value: str) -> int:
    try:
        result = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if result < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return result


def _positive_decimal(value: str) -> float:
    try:
        number = Decimal(value)
        if not number.is_finite() or not Decimal(0) < number <= Decimal(100):
            raise ValueError
        converted = float(number)
        if not math.isfinite(converted) or converted <= 0:
            raise ValueError
        return converted
    except (InvalidOperation, ValueError):
        raise argparse.ArgumentTypeError("must be a finite number greater than 0 and at most 100") from None


def _sample_value(value: str) -> int | str:
    if value == "all":
        return "all"
    if value.endswith("%"):
        try:
            percent = Decimal(value[:-1])
            if not percent.is_finite() or not Decimal(0) < percent <= Decimal(100):
                raise ValueError
            return f"{percent.normalize()}%"
        except (InvalidOperation, ValueError):
            raise argparse.ArgumentTypeError("sample percentage must be greater than 0 and at most 100") from None
    return _positive_int(value)


def normalize_compression_arguments(namespace: argparse.Namespace) -> CompressionOptions:
    """Validate one parsed leaf and return an immutable adapter contract."""
    operation = getattr(namespace, "operation", None)
    owner = getattr(namespace, "_compression_owner", None)
    if operation not in OPERATIONS:
        raise ValueError("Choose a compression operation: " + ", ".join(OPERATIONS))
    if owner not in ("compresser", "mangadl"):
        raise ValueError("Compression parser did not identify its owning adapter")
    target = getattr(namespace, "input", None) or getattr(namespace, "destination", None)
    if target is None:
        raise ValueError("A target is required")
    filters = tuple(getattr(namespace, "url", ()) or ())
    if operation == "recover" and filters:
        raise ValueError("Recovery does not accept URL filters")
    depth = getattr(namespace, "inventory_depth", "headers")
    if operation != "inventory" and depth != "headers":
        raise ValueError("Inventory depth is available only for inventory")
    if operation == "inventory" and depth == "files" and filters:
        raise ValueError("File-depth inventory does not support URL filters")

    mode_value = getattr(namespace, "mode", None) or "lossless"
    modes = ("lossless", "lossy") if mode_value == "both" else (mode_value,)
    requested_formats = getattr(namespace, "format", None) or (
        ["webp"] if operation in ("plan", "estimate") else ["auto"]
    )
    expand_all = "all" in requested_formats
    formats = tuple(
        dict.fromkeys(
            expanded
            for requested in requested_formats
            for expanded in (("auto", "webp", "jpeg", "avif", "png") if requested == "all" else (requested,))
        )
    )
    qualities = tuple(dict.fromkeys(getattr(namespace, "quality", None) or ()))
    if operation in ("plan", "estimate") and not formats:
        formats = ("webp",)
    if operation == "compare" and not formats:
        raise ValueError("Compare requires at least one --format")
    if len(formats) > 1 and operation in ("analyze", "apply"):
        raise ValueError(f"{operation} accepts exactly one format")
    if len(qualities) > 1 and operation in ("analyze", "apply"):
        raise ValueError(f"{operation} accepts exactly one quality")
    perceptual_value = getattr(namespace, "perceptual_target", None)
    perceptual_target = 0.990 if perceptual_value is None else perceptual_value
    if not 0.80 <= perceptual_target <= 1.0:
        raise ValueError("Perceptual target must be between 0.80 and 1.00")
    encoder = getattr(namespace, "encoder", None) or "auto"
    effort_value = getattr(namespace, "effort", None)
    effort = 6 if effort_value is None else effort_value
    recipes: list[RecipeSpec] = []
    for image_format in formats:
        if operation == "preview":
            recipes.append(RecipeSpec(image_format, "lossless", None, perceptual_target, encoder, effort))
            preview_qualities = qualities or (() if image_format == "png" else (90, 80))
            for q in preview_qualities:
                if image_format == "png" and qualities:
                    raise ValueError("PNG does not support a lossy preview quality")
                recipes.append(RecipeSpec(image_format, "lossy", q, perceptual_target, encoder, effort))
            continue
        for mode in modes:
            # A mixed request enumerates supported recipes rather than an impossible
            # Cartesian product. Keep invalid explicit single-mode requests visible.
            if image_format == "avif" and mode == "lossless" and (expand_all or mode_value == "both"):
                continue
            if image_format == "png" and mode != "lossless" and (expand_all or mode_value == "both"):
                continue
            if mode == "lossless":
                if qualities and len(modes) == 1:
                    raise ValueError("Quality is not valid for lossless mode")
                q_values = (None,)
            else:
                q_values = qualities or ((80,) if mode == "lossy" else (None,))
            for q in q_values:
                if mode == "lossy" and image_format == "png":
                    raise ValueError("PNG does not support a lossy quality recipe")
                if mode != "lossy" and q is not None:
                    raise ValueError("Quality is only valid for lossy recipes")
                recipe = RecipeSpec(image_format, mode, q, perceptual_target, encoder, effort)
                if recipe not in recipes:
                    recipes.append(recipe)

    if operation in ("plan", "estimate"):
        policy = "allow-larger" if getattr(namespace, "allow_larger", False) else "keep-if-larger"
        recipes = [replace(recipe, retained_original_policy=policy) for recipe in recipes]
    write = bool(getattr(namespace, "write", False))
    allow_lossy = bool(getattr(namespace, "allow_lossy", False))
    confirmation = getattr(namespace, "confirm_recovery", None)
    if operation == "apply" and not write:
        raise ValueError("apply requires --write")
    if operation == "apply" and any(recipe.mode != "lossless" for recipe in recipes) and not allow_lossy:
        raise ValueError("Lossy or perceptual apply requires --allow-lossy")
    if operation == "recover" and write and not confirmation:
        raise ValueError("recover --write requires --confirm TOKEN")
    if operation == "recover" and confirmation and not write:
        raise ValueError("--confirm requires --write")

    sample = getattr(namespace, "sample", None)
    seed_value = getattr(namespace, "seed", None)
    seed = 0 if seed_value is None else seed_value
    max_images = getattr(namespace, "max_images", None)
    max_trials = getattr(namespace, "max_trials", None)
    max_time = getattr(namespace, "max_time", None)
    accuracy = getattr(namespace, "accuracy_pp", None)
    if operation in ("plan", "estimate") and (
        sample is not None or accuracy is not None and getattr(namespace, "allow_larger", False)
    ):
        raise ValueError("Plan/estimate use --max-images; --sample is for exact analyze/compare operations")
    if operation not in ("plan", "estimate") and any(
        value is not None for value in (max_images, max_trials, max_time, accuracy, getattr(namespace, "plan_id", None))
    ):
        raise ValueError("Plan budgets and --plan are only valid for plan/estimate")
    inventory_policy = getattr(namespace, "inventory_policy", "refresh")
    if operation in ("preview", "apply") and inventory_policy == "snapshot":
        raise ValueError(f"{operation} requires inventory refresh")
    if operation == "apply" and inventory_policy != "refresh":
        raise ValueError("apply requires inventory refresh")

    memory = getattr(namespace, "memory_budget_mib", None)
    if isinstance(memory, int) and memory < 64:
        raise ValueError("Memory budget must be at least 64 MiB")
    threads = getattr(namespace, "threads", 1)
    if threads < 1:
        raise ValueError("Threads must be positive")
    return CompressionOptions(
        operation=operation,
        owner=owner,
        target=Path(target),
        filters=filters,
        recipes=tuple(recipes),
        inventory_depth=depth,
        inventory_policy="trust" if inventory_policy == "snapshot" else inventory_policy,
        sample=None if sample == "all" else sample,
        seed=seed,
        max_images=max_images,
        max_trials=max_trials,
        max_time_seconds=max_time,
        accuracy_pp=accuracy,
        plan_id=getattr(namespace, "plan_id", None),
        plan_recipes_explicit=(
            any(
                getattr(namespace, name, None) is not None
                for name in ("format", "mode", "quality", "perceptual_target", "encoder", "effort")
            )
            if operation in ("plan", "estimate")
            else False
        ),
        plan_seed_explicit=seed_value is not None if operation in ("plan", "estimate") else False,
        plan_budget_explicit=(
            any(value is not None for value in (max_images, max_trials, max_time, accuracy))
            or bool(getattr(namespace, "allow_larger", False))
            if operation in ("plan", "estimate")
            else False
        ),
        threads=threads,
        memory_budget=memory,
        cache_policy=getattr(namespace, "cache_policy", "use"),
        cache_file=getattr(namespace, "cache_file", None),
        scratch_dir=getattr(namespace, "scratch_dir", None),
        output=getattr(namespace, "output", None),
        preview_count=getattr(namespace, "count", 3),
        write=write,
        allow_lossy=allow_lossy,
        allow_larger=bool(getattr(namespace, "allow_larger", False)),
        confirmation=confirmation,
        json=bool(getattr(namespace, "json", False)),
        no_ui=bool(getattr(namespace, "no_ui", False)),
        verbose=int(getattr(namespace, "verbose", 0)),
    )
