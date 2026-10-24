"""Multi-recipe comparison engine, Pareto efficiency analysis, and comparison reports."""

from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field
from pathlib import Path
import shutil
from typing import Any, Sequence

from videocompress.adapters.ffmpeg import FFmpegAdapter
from videocompress.contracts import VideoAsset, VideoRecipe
from videocompress.quality import QualityMetrics, calculate_quality_metrics
from videocompress.sampling import SampleWindow, generate_sample_windows
from videocompress.trials import TrialRecord, TrialStore, aggregate_sample_estimate, run_sample_trials
from videocompress.workspace import VideoWorkspace


@dataclass(frozen=True, slots=True)
class RecipeComparisonResult:
    """Evaluated performance and quality metrics for a single candidate recipe."""

    recipe_id: str
    encoder: str
    codec: str
    cq: float
    measured_mean_bps: int
    predicted_container_bytes: int
    predicted_savings_bytes: int
    predicted_savings_pct: float
    fps_throughput: float
    encode_seconds: float
    quality_ssim: float | None
    quality_psnr: float | None
    quality_vmaf: float | None
    is_pareto_efficient: bool
    rank: int
    caveats: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipe_id": self.recipe_id,
            "encoder": self.encoder,
            "codec": self.codec,
            "cq": self.cq,
            "measured_mean_bps": self.measured_mean_bps,
            "predicted_container_bytes": self.predicted_container_bytes,
            "predicted_savings_bytes": self.predicted_savings_bytes,
            "predicted_savings_pct": round(self.predicted_savings_pct, 2),
            "fps_throughput": round(self.fps_throughput, 1),
            "encode_seconds": round(self.encode_seconds, 3),
            "quality_ssim": round(self.quality_ssim, 4) if self.quality_ssim is not None else None,
            "quality_psnr": round(self.quality_psnr, 2) if self.quality_psnr is not None else None,
            "quality_vmaf": round(self.quality_vmaf, 2) if self.quality_vmaf is not None else None,
            "is_pareto_efficient": self.is_pareto_efficient,
            "rank": self.rank,
            "caveats": list(self.caveats),
        }


@dataclass(frozen=True, slots=True)
class AssetComparisonReport:
    """Side-by-side recipe comparison report for a specific video asset."""

    source_id: str
    source_bytes: int
    duration_seconds: float
    recipe_results: list[RecipeComparisonResult]
    recommended_recipe_id: str | None
    created_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_bytes": self.source_bytes,
            "duration_seconds": self.duration_seconds,
            "recommended_recipe_id": self.recommended_recipe_id,
            "recipe_results": [r.to_dict() for r in self.recipe_results],
            "created_at": self.created_at,
        }


def compute_pareto_efficiency(
    results: Sequence[RecipeComparisonResult],
) -> list[RecipeComparisonResult]:
    """Identify Pareto-efficient recipes (not strictly dominated in savings, quality, and speed).

    Ranks candidate recipes by composite efficiency score.
    """
    if not results:
        return []

    is_efficient_list: list[bool] = []
    for i, curr in enumerate(results):
        dominated = False
        curr_ssim = curr.quality_ssim if curr.quality_ssim is not None else 0.0
        for j, other in enumerate(results):
            if i == j:
                continue
            other_ssim = other.quality_ssim if other.quality_ssim is not None else 0.0
            # other dominates curr if >= in all metrics and strictly > in at least one
            better_or_equal = (
                other.predicted_savings_pct >= curr.predicted_savings_pct
                and other_ssim >= curr_ssim
                and other.fps_throughput >= curr.fps_throughput
            )
            strictly_better = (
                other.predicted_savings_pct > curr.predicted_savings_pct
                or other_ssim > curr_ssim
                or other.fps_throughput > curr.fps_throughput
            )
            if better_or_equal and strictly_better:
                dominated = True
                break
        is_efficient_list.append(not dominated)

    # Calculate ranking composite score: savings_pct * quality_weight
    scored_results: list[tuple[float, RecipeComparisonResult]] = []
    for idx, (res, eff) in enumerate(zip(results, is_efficient_list)):
        quality_factor = res.quality_ssim if res.quality_ssim is not None else 0.90
        # Pareto-efficient candidates receive ranking priority
        score = res.predicted_savings_pct * (quality_factor ** 2) * (1.1 if eff else 0.9)
        scored_results.append((score, res, eff))

    # Sort descending by score
    scored_results.sort(key=lambda x: x[0], reverse=True)

    final_results: list[RecipeComparisonResult] = []
    for rank_idx, (_, res, eff) in enumerate(scored_results, start=1):
        final_results.append(
            RecipeComparisonResult(
                recipe_id=res.recipe_id,
                encoder=res.encoder,
                codec=res.codec,
                cq=res.cq,
                measured_mean_bps=res.measured_mean_bps,
                predicted_container_bytes=res.predicted_container_bytes,
                predicted_savings_bytes=res.predicted_savings_bytes,
                predicted_savings_pct=res.predicted_savings_pct,
                fps_throughput=res.fps_throughput,
                encode_seconds=res.encode_seconds,
                quality_ssim=res.quality_ssim,
                quality_psnr=res.quality_psnr,
                quality_vmaf=res.quality_vmaf,
                is_pareto_efficient=eff,
                rank=rank_idx,
                caveats=res.caveats,
            )
        )

    return final_results


def run_recipe_comparison(
    asset: VideoAsset,
    canonical_path: str,
    candidate_recipes: Sequence[VideoRecipe],
    workspace: VideoWorkspace,
    schedule: str = "s3",
    window_duration_seconds: float = 10.0,
    compute_quality: bool = True,
    min_savings_pct: float | None = None,
) -> AssetComparisonReport:
    """Execute side-by-side empirical trial comparison across candidate recipes."""
    canonical_map = {asset.source_id: canonical_path}
    trial_store = TrialStore(workspace.trials_db)
    source_p = Path(canonical_path)

    raw_results: list[RecipeComparisonResult] = []

    for recipe in candidate_recipes:
        # Run / retrieve sample trials for this recipe
        records, _ = run_sample_trials(
            assets=[asset],
            canonical_paths=canonical_map,
            recipe=recipe,
            workspace=workspace,
            schedule=schedule,
            window_duration_seconds=window_duration_seconds,
        )

        st = source_p.stat() if source_p.exists() else None
        stat_fp = f"{st.st_mtime_ns}:{st.st_size}" if st else ""
        trials_for_recipe = trial_store.get_trials_for_asset(asset.source_id, stat_fp, recipe.recipe_id)

        pred = aggregate_sample_estimate(
            asset=asset,
            recipe=recipe,
            trials=trials_for_recipe,
            min_savings_pct=min_savings_pct,
        )

        # Average throughput and encode time across trials
        avg_fps = sum(t.fps_throughput for t in trials_for_recipe) / len(trials_for_recipe) if trials_for_recipe else 0.0
        total_sec = sum(t.encode_seconds for t in trials_for_recipe)

        # Evaluate frame-aligned quality metrics on sample window 0 if requested
        qm: QualityMetrics | None = None
        if compute_quality and trials_for_recipe:
            # We encode window 0 to temp scratch clip for quality scoring
            w0 = SampleWindow(0, trials_for_recipe[0].window_start, trials_for_recipe[0].window_duration)
            scratch_q_dir = workspace.root / "scratch" / f"qual_{asset.source_id}_{recipe.recipe_id}"
            adapter = FFmpegAdapter()
            try:
                sample_res = adapter.encode_sample_clip(
                    source_path=source_p,
                    recipe=recipe,
                    window=w0,
                    scratch_dir=scratch_q_dir,
                )
                qm = calculate_quality_metrics(
                    source_path=source_p,
                    sample_path=sample_res.sample_path,
                    window=w0,
                )
            except Exception:
                qm = None
            finally:
                if scratch_q_dir.exists():
                    shutil.rmtree(scratch_q_dir, ignore_errors=True)

        raw_results.append(
            RecipeComparisonResult(
                recipe_id=recipe.recipe_id,
                encoder=recipe.encoder,
                codec=recipe.codec,
                cq=recipe.rate_control_value,
                measured_mean_bps=pred.measured_mean_video_bps,
                predicted_container_bytes=pred.predicted_output_container_bytes,
                predicted_savings_bytes=pred.predicted_gross_saved_bytes,
                predicted_savings_pct=pred.predicted_savings_pct,
                fps_throughput=avg_fps,
                encode_seconds=total_sec,
                quality_ssim=qm.ssim_all if qm else None,
                quality_psnr=qm.psnr_all if qm else None,
                quality_vmaf=qm.vmaf_mean if qm else None,
                is_pareto_efficient=True,
                rank=1,
                caveats=qm.caveats if qm else (),
            )
        )

    # Compute Pareto efficiency and ranks
    ranked_results = compute_pareto_efficiency(raw_results)
    recommended = ranked_results[0].recipe_id if ranked_results else None

    report = AssetComparisonReport(
        source_id=asset.source_id,
        source_bytes=asset.file_bytes,
        duration_seconds=asset.duration_seconds,
        recipe_results=ranked_results,
        recommended_recipe_id=recommended,
    )

    # Persist report to workspace/reports/
    report_file = workspace.reports_dir / f"compare_{asset.source_id}_{int(datetime.datetime.now().timestamp())}.json"
    try:
        import json
        report_file.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    except OSError:
        pass

    return report
