"""
Estimation planning, candidate freezing, and sampling schedule generation.
Follows INTEGRATION_CONTRACTS.md §4, §5 and IMPLEMENTATION_PLAN.md §5, §6.

Freezes eligible sources, recipes, and deterministic sampling windows into an immutable
plan artifact. Zero encodes are executed during planning.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Sequence

from .contracts import SamplingWindow, VideoEstimationPlan, VideoRecipe
from .inventory import InventoryReport, scan_inventory
from .recipes import get_recipe
from .workspace import VideoWorkspace, resolve_workspace


def generate_sampling_windows(
    source_id: str,
    duration_seconds: float,
    strategy: str = "uniform_3x20",
) -> tuple[SamplingWindow, ...]:
    """
    Generate deterministic temporal sampling intervals across a source video's playable duration.
    Windows avoid boundary intro/outro black frames and credits by default.
    """
    dur = max(0.0, duration_seconds)
    if dur <= 0.0 or strategy == "none":
        return ()

    windows: list[SamplingWindow] = []

    if strategy in ("uniform_3x20", "uniform_3x10"):
        clip_len = 20.0 if "20" in strategy else 10.0
        if dur <= clip_len * 1.5:
            # Very short video: single sample window covering up to clip_len
            windows.append(
                SamplingWindow(
                    source_id=source_id,
                    window_index=0,
                    start_seconds=0.0,
                    duration_seconds=min(dur, clip_len),
                    weight=1.0,
                    purpose="uniform",
                )
            )
        else:
            # 3 windows placed at 10%, 45%, and 80% through the video
            positions = [0.10, 0.45, 0.80]
            for idx, pos in enumerate(positions):
                start = max(0.0, pos * dur)
                # Ensure window does not overshoot end of file
                actual_duration = min(clip_len, max(1.0, dur - start))
                windows.append(
                    SamplingWindow(
                        source_id=source_id,
                        window_index=idx,
                        start_seconds=round(start, 3),
                        duration_seconds=round(actual_duration, 3),
                        weight=1.0,
                        purpose="uniform",
                    )
                )

    elif strategy in ("uniform_5x20", "uniform_5x10"):
        clip_len = 20.0 if "20" in strategy else 10.0
        if dur <= clip_len * 2:
            windows.append(
                SamplingWindow(
                    source_id=source_id,
                    window_index=0,
                    start_seconds=0.0,
                    duration_seconds=min(dur, clip_len),
                    weight=1.0,
                    purpose="uniform",
                )
            )
        else:
            positions = [0.08, 0.28, 0.48, 0.68, 0.88]
            for idx, pos in enumerate(positions):
                start = max(0.0, pos * dur)
                actual_duration = min(clip_len, max(1.0, dur - start))
                windows.append(
                    SamplingWindow(
                        source_id=source_id,
                        window_index=idx,
                        start_seconds=round(start, 3),
                        duration_seconds=round(actual_duration, 3),
                        weight=1.0,
                        purpose="uniform",
                    )
                )

    return tuple(windows)


def build_estimation_plan(
    target: Path | str,
    recipes: Sequence[VideoRecipe] | None = None,
    workspace_root: Path | str | None = None,
    min_video_bitrate: int | str | None = None,
    min_resolution: str | tuple[int, int] | None = None,
    min_size: int | str | None = None,
    min_duration: float | str | None = None,
    sampling_strategy: str = "uniform_3x20",
    work_budget_seconds: float | None = None,
    inventory_report: InventoryReport | None = None,
    force_refresh: bool = False,
) -> VideoEstimationPlan:
    """
    Freeze an eligible population, target recipes, and sampling schedule into an immutable plan.
    Saves the plan JSON artifact to `<workspace>/plans/<plan_id>.json`.
    """
    ws = resolve_workspace(target, parent=workspace_root)
    ws.plans_dir.mkdir(parents=True, exist_ok=True)

    if inventory_report is None:
        inventory_report = scan_inventory(
            target=target,
            workspace_root=ws.root,
            min_video_bitrate=min_video_bitrate,
            min_resolution=min_resolution,
            min_size=min_size,
            min_duration=min_duration,
            inventory_depth="probe",
            force_refresh=force_refresh,
        )

    resolved_recipes = tuple(recipes) if recipes else (get_recipe("av1_nvenc_cq30"),)

    # Filter to eligible source IDs and gather duration for sampling windows
    eligible_sources: list[tuple[str, float]] = []
    for rec in inventory_report.per_source_records:
        elig = rec.get("eligibility", {})
        if elig.get("status") == "eligible":
            sid = str(rec["source_id"])
            dur = float(rec.get("duration_seconds") or 0.0)
            eligible_sources.append((sid, dur))

    eligible_sids = tuple(s[0] for s in eligible_sources)

    # Generate sampling windows
    all_windows: list[SamplingWindow] = []
    for sid, dur in eligible_sources:
        src_windows = generate_sampling_windows(sid, dur, strategy=sampling_strategy)
        all_windows.extend(src_windows)

    # Derive deterministic plan ID
    hasher = hashlib.sha256()
    hasher.update(str(target).encode("utf-8"))
    for sid in sorted(eligible_sids):
        hasher.update(sid.encode("utf-8"))
    for r in sorted(resolved_recipes, key=lambda x: x.recipe_id):
        hasher.update(r.recipe_id.encode("utf-8"))
    hasher.update(sampling_strategy.encode("utf-8"))
    plan_id = f"plan-{hasher.hexdigest()[:16]}"

    created_at = datetime.now(timezone.utc).isoformat()

    plan = VideoEstimationPlan(
        plan_id=plan_id,
        target_scope=str(target),
        workspace_parent=str(ws.root.parent),
        source_ids=eligible_sids,
        recipes=resolved_recipes,
        sampling_windows=tuple(all_windows),
        work_budget_seconds=work_budget_seconds,
        created_at=created_at,
    )

    # Save immutable plan artifact
    plan_file = ws.plans_dir / f"{plan_id}.json"
    plan_file.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")

    return plan
