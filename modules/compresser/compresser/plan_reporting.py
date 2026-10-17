"""Compact, human-readable summaries for saved estimation plans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path

from termdash.table import render_table_panels, wrap_display_text
from termdash.utils import color_text

from .estimation_models import EstimationPlan

_FORMAT_ORDER = ("auto", "webp", "jpeg", "avif", "png", "keep")
_FORMAT_NAMES = {"auto": "AUTO", "webp": "WebP", "jpeg": "JPEG", "avif": "AVIF", "png": "PNG", "keep": "Keep"}
_DEFAULT_ENCODER = "auto"
_DEFAULT_EFFORT = 6


@dataclass(frozen=True, slots=True)
class PlanSummary:
    """Presentation facts derived from an immutable plan."""

    title: str
    overview: tuple[str, ...]
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    annotations: tuple[str, ...]
    warnings: tuple[str, ...]
    plan_id: str


def _duration(seconds: float) -> str:
    minutes = max(1, math.ceil(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    return f"{minutes} min"


def _age(seconds: float) -> str:
    minutes = max(0, int(seconds // 60))
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    return f"{minutes}m"


def _format_name(value: str) -> str:
    normalized = value.casefold()
    return _FORMAT_NAMES.get(normalized, value.upper())


def _count_label(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count:,} {singular if count == 1 else plural or singular + 's'}"


def _format_order(formats: set[str]) -> tuple[str, ...]:
    known = [name for name in _FORMAT_ORDER if name in formats]
    unknown = sorted(formats - set(_FORMAT_ORDER))
    return tuple((*known, *unknown))


def _recipe_annotations(plan: EstimationPlan) -> list[str]:
    annotations: list[str] = []
    groups: dict[tuple[str, str, int | None, float], set[tuple[str, int]]] = {}
    for recipe in plan.recipes:
        settings = (recipe.encoder, recipe.effort)
        if settings != (_DEFAULT_ENCODER, _DEFAULT_EFFORT):
            groups.setdefault(
                (recipe.format.casefold(), recipe.mode, recipe.quality, recipe.perceptual_target), set()
            ).add(settings)
    for (format_name, mode, quality, target), settings in groups.items():
        rendered = ", ".join(f"{encoder}, effort {effort}" for encoder, effort in sorted(settings))
        descriptor = f"{_format_name(format_name)} {mode}"
        if quality is not None:
            descriptor += f" {quality}"
        elif mode == "perceptual":
            descriptor += f" SSIM ≥ {target:.3f}"
        annotations.append(f"{descriptor}: {rendered}.")
    return annotations


def build_plan_summary(
    plan: EstimationPlan,
    *,
    population_count: int,
    now: datetime | None = None,
) -> PlanSummary:
    """Build concise plan facts without reading files or probing the terminal."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    completed = datetime.fromisoformat(plan.inventory_completed)
    if completed.tzinfo is None:
        completed = completed.replace(tzinfo=timezone.utc)
    elapsed = max(0.0, (current - completed).total_seconds())

    formats = {recipe.format.casefold() for recipe in plan.recipes}
    ordered_formats = _format_order(formats)
    modes = {recipe.mode for recipe in plan.recipes}
    has_lossless = "lossless" in modes
    has_lossy = "lossy" in modes
    has_perceptual = "perceptual" in modes
    headers = ["Format"]
    if has_lossless:
        headers.append("Lossless")
    if has_lossy:
        headers.append("Lossy qualities")
    if has_perceptual:
        headers.append("Perceptual target")

    rows: list[tuple[str, ...]] = []
    for format_name in ordered_formats:
        recipes = [recipe for recipe in plan.recipes if recipe.format.casefold() == format_name]
        row = [_format_name(format_name)]
        if has_lossless:
            row.append(
                "Yes*"
                if format_name == "jpeg" and any(r.mode == "lossless" for r in recipes)
                else "Yes" if any(r.mode == "lossless" for r in recipes) else "—"
            )
        if has_lossy:
            qualities = list(
                dict.fromkeys(
                    str(recipe.quality) for recipe in recipes if recipe.mode == "lossy" and recipe.quality is not None
                )
            )
            row.append(", ".join(qualities) if qualities else "—")
        if has_perceptual:
            targets = list(dict.fromkeys(recipe.perceptual_target for recipe in recipes if recipe.mode == "perceptual"))
            row.append(", ".join(f"SSIM ≥ {target:.3f}" for target in targets) if targets else "—")
        rows.append(tuple(row))

    group_count = len(plan.strata)
    covered = max(0, group_count - len(set(plan.coverage_gaps)))
    recipe_count = len(plan.recipes)
    pilot_count = len(plan.pilot_member_ids)
    nominal_measurements = sum(quota.total for quota in plan.recipe_quotas)
    overview = (
        f"{_count_label(population_count, 'image')} · {_count_label(recipe_count, 'recipe')} · "
        f"{_count_label(covered, 'group')} covered",
        f"Inventory: {plan.depth} · saved {_age(elapsed)} ago",
        (
            f"Limits   {_count_label(plan.budget.max_images, 'image')} · "
            f"{_count_label(plan.budget.max_new_encodes, 'new encode')} · "
            f"{_duration(plan.budget.max_runtime_seconds)} active time"
        ),
        f"Pilot    {_count_label(pilot_count, 'shared image')} across {_count_label(recipe_count, 'recipe')}",
    )

    annotations = _recipe_annotations(plan)
    if any(recipe.format.casefold() == "jpeg" and recipe.mode == "lossless" for recipe in plan.recipes):
        annotations.append("* JPEG lossless requires jpegtran and JPEG source images.")
    if plan.filters:
        annotations.append("Selection filters: " + ", ".join(plan.filters))
    if plan.accuracy_pp is not None:
        annotations.append(f"Accuracy goal: {plan.accuracy_pp:g} pp; not a certification.")
    if plan.allow_larger:
        annotations.append("Larger outputs are allowed by this plan.")

    warnings: list[str] = []
    if plan.depth == "files":
        warnings.append("Files-only inventory is unverified; image headers and contents were not checked.")
    if plan.coverage_gaps:
        gaps = ", ".join(plan.coverage_gaps)
        warnings.append(f"Coverage gaps: {gaps}")
    if recipe_count and nominal_measurements >= 0.80 * plan.budget.max_new_encodes:
        warning = f"Encode budget is tight: the pilot schedules {nominal_measurements:,} image/recipe measurements. "
        if any(recipe.format.casefold() == "auto" for recipe in plan.recipes):
            warning += "AUTO may need multiple encodes per measurement; "
        warning += "cached results may reduce new encodes."
        warnings.append(warning)

    return PlanSummary(
        title=f"Compression plan saved · {Path(plan.root).name}",
        overview=overview,
        headers=tuple(headers),
        rows=tuple(rows),
        annotations=tuple(annotations),
        warnings=tuple(warnings),
        plan_id=plan.plan_id,
    )


def render_plan_summary(
    summary: PlanSummary,
    *,
    report_path: str | Path | None,
    width: int,
    color: bool,
) -> str:
    """Render the compact plan summary at a bounded display width."""
    width = max(2, width)
    paint = color_text if color else lambda text, _tone: text
    lines = wrap_display_text(paint(summary.title, "cyan"), width)
    for index, fact in enumerate(summary.overview):
        if index == 2:
            lines.append("")
        lines.extend(wrap_display_text(fact, width))

    lines.append("")
    table = render_table_panels(
        summary.headers,
        summary.rows,
        identity_columns=(0,),
        max_width=width,
        alignments=["left"] * len(summary.headers),
    )
    for panel in table:
        lines.extend(panel.splitlines())
    for annotation in summary.annotations:
        lines.extend(wrap_display_text(annotation, width))
    for warning in summary.warnings:
        lines.extend(wrap_display_text(paint(f"WARNING: {warning}", "yellow"), width))

    lines.append("")
    lines.extend(wrap_display_text(f"Plan     {summary.plan_id}", width))
    if report_path is not None:
        lines.extend(wrap_display_text(f"Report   {report_path}", width))
    lines.extend(wrap_display_text("Planning only; no images encoded.", width))
    return "\n".join(lines)
