"""Compact, human-readable summaries for saved estimation plans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Sequence

from termdash.table import render_table_panels, wrap_display_text
from termdash.utils import color_text, format_bytes_decimal

from .estimation_models import EstimationPlan, EstimationResult

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


def _format_strata_group(strata_keys: Sequence[str]) -> str:
    from collections import defaultdict

    by_fmt: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for k in strata_keys:
        parts = k.split("|")
        fmt = _format_name(parts[0].lower())
        if len(parts) >= 3 and parts[2].startswith("log2:"):
            exp_str = parts[2][5:]
            if exp_str.isdigit():
                exp = int(exp_str)
                size_str = f"~{format_bytes_decimal(1 << exp)}"
                by_fmt[fmt].append((exp, size_str))
                continue
            elif exp_str == "all":
                by_fmt[fmt].append((-1, "all sizes"))
                continue
        by_fmt[fmt].append((999, k))

    parts_out = []
    for fmt, items in sorted(by_fmt.items()):
        items_sorted = [s for _, s in sorted(items, key=lambda x: x[0])]
        parts_out.append(f"{fmt} ({', '.join(items_sorted)})")
    return "; ".join(parts_out)


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
    quota_totals = {quota.recipe_id: quota.total for quota in plan.recipe_quotas}
    if quota_totals and len(set(quota_totals.values())) > 1:
        recipes_by_identity = {recipe.identity: recipe for recipe in plan.recipes}
        allocations = []
        for identity, total in quota_totals.items():
            recipe = recipes_by_identity.get(identity)
            if recipe is None:
                continue
            descriptor = f"{_format_name(recipe.format)} {recipe.mode}"
            if recipe.quality is not None:
                descriptor += f" {recipe.quality}"
            elif recipe.mode == "perceptual":
                descriptor += f" SSIM ≥ {recipe.perceptual_target:.3f}"
            if recipe.encoder != _DEFAULT_ENCODER or recipe.effort != _DEFAULT_EFFORT:
                descriptor += f" ({recipe.encoder}, effort {recipe.effort})"
            allocations.append(f"{descriptor}: {total:,}")
        if allocations:
            annotations.append(
                "Pilot allocations: "
                + "; ".join(allocations)
                + f" ({_count_label(sum(quota_totals.values()), 'image/recipe measurement')})."
            )
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


@dataclass(frozen=True, slots=True)
class EstimateSummary:
    title: str
    overview: tuple[str, ...]
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    annotations: tuple[str, ...]
    warnings: tuple[str, ...]
    plan_id: str
    stopping_reason: str
    row_tones: tuple[str | None, ...] = ()
    example_commands: tuple[str, ...] = ()


def build_estimate_summary(
    plan: EstimationPlan,
    result: EstimationResult,
    *,
    population_count: int,
    now: datetime | None = None,
    sort: bool = True,
    owner: str = "mangadl",
    invocation_args: object | None = None,
) -> EstimateSummary:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    completed = datetime.fromisoformat(plan.inventory_completed)
    if completed.tzinfo is None:
        completed = completed.replace(tzinfo=timezone.utc)

    overview = (
        f"Target   {Path(plan.root).name or str(plan.root)} · {_count_label(population_count, 'member')}",
        f"Status   {result.stopping_reason} ({result.stage}) · {_count_label(result.total_observations, 'observation')} in plan",
        f"Runs     {result.new_encodes:,} new encodes · {result.cache_hits:,} cache hits · {result.newly_admitted_sources:,} sources admitted",
    )

    headers = ["Recipe", "Format", "Mode", "Quality", "Est. Saved", "Savings %", "StdDev", "Gaps"]
    recipes_by_id = {r.identity: r for r in plan.recipes}

    estimates = list(result.estimates)
    if sort:
        estimates.sort(
            key=lambda est: (
                est.estimated_saved_bytes is not None,
                est.estimated_saved_bytes if est.estimated_saved_bytes is not None else -float("inf"),
                est.savings_percent if est.savings_percent is not None else -float("inf"),
                1 if recipes_by_id.get(est.recipe_id) and recipes_by_id.get(est.recipe_id).format != "auto" else 0,
            ),
            reverse=True,
        )

    best_lossy_est = None
    best_lossless_est = None
    for est in estimates:
        r = recipes_by_id.get(est.recipe_id)
        if not r or est.estimated_saved_bytes is None or est.estimated_saved_bytes <= 0:
            continue
        if r.mode == "lossy":
            if best_lossy_est is None or est.estimated_saved_bytes > (best_lossy_est.estimated_saved_bytes or 0):
                best_lossy_est = est
        elif r.mode == "lossless":
            if best_lossless_est is None or est.estimated_saved_bytes > (best_lossless_est.estimated_saved_bytes or 0):
                best_lossless_est = est
            elif est.estimated_saved_bytes == (best_lossless_est.estimated_saved_bytes or 0):
                prev_r = recipes_by_id.get(best_lossless_est.recipe_id)
                if prev_r and prev_r.format == "auto" and r.format != "auto":
                    best_lossless_est = est

    rows = []
    row_tones: list[str | None] = []
    for est in estimates:
        r = recipes_by_id.get(est.recipe_id)
        fmt = _format_name(r.format) if r else "—"
        mode = r.mode if r else "—"
        q = str(r.quality) if r and r.quality is not None else "—"
        from .reporting import binary_bytes

        saved = binary_bytes(round(est.estimated_saved_bytes)) if est.estimated_saved_bytes is not None else "—"
        pct = f"{est.savings_percent:.1f}%" if est.savings_percent is not None else "—"
        stddev = (
            f"±{binary_bytes(round(math.sqrt(est.variance)))}"
            if est.variance is not None and est.variance >= 0
            else "—"
        )
        if not est.gaps:
            gaps_desc = "none"
        elif any("unresolved" in g for g in est.gaps):
            gaps_desc = "unresolved"
        elif any("unsampled remainder" in g for g in est.gaps):
            tot = len(est.groups) if est.groups else 1
            unsampled_cnt = sum(1 for g in est.groups if any("unsampled remainder" in gap for gap in g.gaps))
            gaps_desc = f"{tot - unsampled_cnt}/{tot} confirmed"
        elif any("singleton" in g for g in est.gaps):
            tot = len(est.groups) if est.groups else 1
            singleton_cnt = sum(1 for g in est.groups if any("singleton" in gap for gap in g.gaps))
            gaps_desc = f"{tot - singleton_cnt}/{tot} (singleton)"
        else:
            gaps_desc = "incomplete"

        recipe_base = f"{fmt} {mode}" + (f" {q}" if q != "—" else "")
        if est is best_lossy_est and len(estimates) > 1:
            recipe_label = f"{recipe_base} (best lossy)"
            row_tones.append("green")
        elif est is best_lossless_est and len(estimates) > 1:
            recipe_label = f"{recipe_base} (best lossless)"
            row_tones.append("cyan")
        else:
            recipe_label = recipe_base
            row_tones.append(None)

        rows.append(
            [
                recipe_label,
                fmt,
                mode,
                q,
                saved,
                pct,
                stddev,
                gaps_desc,
            ]
        )

    annotations = [
        "Fixed-design stratified estimate; variance represents sample variation.",
    ]
    if result.stopping_reason != "complete":
        if result.stopping_reason == "missing_group_coverage":
            budget_str = (
                f"{plan.budget.max_new_encodes:,} trials" if plan.budget and plan.budget.max_new_encodes else "budget"
            )
            annotations.append(
                f"Incomplete run (missing_group_coverage); plan budget ({budget_str}) was exhausted during design allocation. "
                "Create a new plan with -T (e.g. -T 2500) for full confirmation and StdDev."
            )
        elif result.stopping_reason in ("max_trials_reached", "deadline_exceeded", "pilot_incomplete"):
            annotations.append(
                f"Incomplete run ({result.stopping_reason}); rerun estimate with additional budget to continue."
            )
        else:
            annotations.append(f"Incomplete run ({result.stopping_reason}).")

    from .reporting import binary_bytes

    if best_lossy_est and len(estimates) > 1:
        r = recipes_by_id.get(best_lossy_est.recipe_id)
        if r and best_lossy_est.estimated_saved_bytes is not None:
            sav = binary_bytes(round(best_lossy_est.estimated_saved_bytes))
            pct = f"{best_lossy_est.savings_percent:.1f}%" if best_lossy_est.savings_percent is not None else ""
            q_str = f" q{r.quality}" if r.quality is not None else ""
            annotations.append(f"Best lossy option: {_format_name(r.format)} lossy{q_str} ({sav} saved, {pct})")
    if best_lossless_est and len(estimates) > 1:
        r = recipes_by_id.get(best_lossless_est.recipe_id)
        if r and best_lossless_est.estimated_saved_bytes is not None:
            sav = binary_bytes(round(best_lossless_est.estimated_saved_bytes))
            pct = f"{best_lossless_est.savings_percent:.1f}%" if best_lossless_est.savings_percent is not None else ""
            annotations.append(f"Best lossless option: {_format_name(r.format)} lossless ({sav} saved, {pct})")

    unsampled_strata = sorted(
        {gap.rsplit(": ", 1)[0] for est in result.estimates for gap in est.gaps if "unsampled remainder" in gap}
    )
    if unsampled_strata:
        annotations.append(f"Unconfirmed strata (pilot-projected): {_format_strata_group(unsampled_strata)}")

    unresolved_by_recipe: dict[str, list[str]] = {}
    for est in result.estimates:
        r = recipes_by_id.get(est.recipe_id)
        r_name = (
            (f"{_format_name(r.format)} {r.mode}" + (f" {r.quality}" if r and r.quality is not None else ""))
            if r
            else est.recipe_id[:8]
        )
        failures = sorted({gap.rsplit(": ", 1)[0] for gap in est.gaps if "unresolved" in gap})
        if failures:
            unresolved_by_recipe[r_name] = failures
    if unresolved_by_recipe:
        for r_name, strata in unresolved_by_recipe.items():
            if "lossless" in r_name.lower() and "jpeg" in r_name.lower():
                annotations.append(f"Unresolved in {r_name}: all trials failed (requires -A cli-jpegtran)")
            else:
                strata_desc = _format_strata_group(strata)
                annotations.append(f"Unresolved in {r_name} (failed trials): {strata_desc}")

    warnings = []
    if plan.coverage_gaps:
        warnings.append(f"Coverage gaps: {', '.join(plan.coverage_gaps)}")

    prog = "mangadl compress" if owner == "mangadl" else "compresser"
    target_raw = getattr(invocation_args, "destination", None) or getattr(invocation_args, "input", None) or plan.root
    flag_t = f"-d {target_raw}" if owner == "mangadl" else f"-i {target_raw}"
    ws = getattr(invocation_args, "workspace", None)
    flag_ws = f" -I {ws}" if ws else ""
    threads = getattr(invocation_args, "threads", None)
    flag_th = f" -t {threads}" if threads and threads > 1 else ""

    lossy_qs = sorted(
        {r.quality for r in plan.recipes if r.mode == "lossy" and r.quality is not None},
        reverse=True,
    )
    qs_str = " ".join(str(q) for q in lossy_qs)

    current_budget = plan.budget.max_new_encodes or 2000
    deeper_trials = max(3000, int(current_budget * 1.5))

    example_commands = []
    if best_lossy_est and len(estimates) > 1:
        r = recipes_by_id.get(best_lossy_est.recipe_id)
        if r:
            fmt = r.format.lower()
            q_flag = f" -q {qs_str}" if qs_str else (f" -q {r.quality}" if r.quality is not None else "")
            example_commands.append(
                f"• In-depth estimate for best lossy option ({_format_name(fmt)} with evaluated qualities):\n"
                f"    {prog} estimate {flag_t}{flag_ws} -f {fmt} -m lossy{q_flag} -T {deeper_trials}{flag_th}"
            )
            example_commands.append(
                f"• Visual quality preview (sample side-by-side images before applying):\n"
                f"    {prog} preview {flag_t}{flag_ws} -f {fmt} -m lossy{q_flag} -c 10"
            )
    if best_lossless_est and len(estimates) > 1:
        r = recipes_by_id.get(best_lossless_est.recipe_id)
        if r:
            fmt = r.format.lower()
            example_commands.append(
                f"• In-depth estimate for best lossless option ({_format_name(fmt)} lossless):\n"
                f"    {prog} estimate {flag_t}{flag_ws} -f {fmt} -m lossless -T {deeper_trials}{flag_th}"
            )

    return EstimateSummary(
        title=f"Compression estimate · {Path(plan.root).name}",
        overview=overview,
        headers=tuple(headers),
        rows=tuple(tuple(r) for r in rows),
        annotations=tuple(annotations),
        warnings=tuple(warnings),
        plan_id=plan.plan_id,
        stopping_reason=result.stopping_reason,
        row_tones=tuple(row_tones),
        example_commands=tuple(example_commands),
    )


def render_estimate_summary(
    summary: EstimateSummary,
    *,
    report_path: str | Path | None,
    width: int,
    color: bool,
) -> str:
    width = max(2, width)
    paint = color_text if color else lambda text, _tone: text
    lines = wrap_display_text(paint(summary.title, "cyan"), width)
    for index, fact in enumerate(summary.overview):
        if index == 2:
            lines.append("")
        lines.extend(wrap_display_text(fact, width))

    lines.append("")
    if summary.rows:
        headers = summary.headers
        rows = summary.rows
        alignments = ["left", "left", "left", "right", "right", "right", "right", "left"]
        if width < 100 and len(headers) == 8:
            headers = ("Recipe", "Est. Saved", "Savings %", "StdDev", "Gaps")
            rows = tuple((r[0], r[4], r[5], r[6], r[7]) for r in rows)
            alignments = ["left", "right", "right", "right", "left"]

        if color and summary.row_tones:
            colored_rows = []
            for idx, r in enumerate(rows):
                tone = summary.row_tones[idx] if idx < len(summary.row_tones) else None
                if tone:
                    row_list = list(r)
                    row_list[0] = paint(row_list[0], tone)
                    if len(row_list) == 5:
                        row_list[1] = paint(row_list[1], tone)
                        row_list[2] = paint(row_list[2], tone)
                    elif len(row_list) == 8:
                        row_list[4] = paint(row_list[4], tone)
                        row_list[5] = paint(row_list[5], tone)
                    colored_rows.append(tuple(row_list))
                else:
                    colored_rows.append(r)
            rows = tuple(colored_rows)

        table = render_table_panels(
            headers,
            rows,
            identity_columns=(0,),
            max_width=width,
            alignments=alignments,
        )
        for panel in table:
            lines.extend(panel.splitlines())
    for annotation in summary.annotations:
        if color and annotation.startswith("Best lossy option:"):
            lines.extend(wrap_display_text(paint(annotation, "green"), width))
        elif color and annotation.startswith("Best lossless option:"):
            lines.extend(wrap_display_text(paint(annotation, "cyan"), width))
        else:
            lines.extend(wrap_display_text(annotation, width))
    for warning in summary.warnings:
        lines.extend(wrap_display_text(paint(f"WARNING: {warning}", "yellow"), width))

    if summary.example_commands:
        lines.append("")
        lines.extend(wrap_display_text(paint("Next-step commands (deeper analysis on best options):", "cyan"), width))
        for cmd_entry in summary.example_commands:
            for cmd_line in cmd_entry.splitlines():
                if cmd_line.strip().startswith(("mangadl", "compresser")):
                    lines.extend(wrap_display_text(paint(cmd_line, "green"), width))
                else:
                    lines.extend(wrap_display_text(cmd_line, width))

    lines.append("")
    lines.extend(wrap_display_text(f"Plan     {summary.plan_id}", width))
    if report_path is not None:
        lines.extend(wrap_display_text(f"Report   {report_path}", width))
    return "\n".join(lines)
