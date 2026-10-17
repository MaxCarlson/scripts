#!/usr/bin/env python3
"""
TermDash UI integration, live in-place progress, and post-processing reports.
"""

from __future__ import annotations

import os
import sys
import time
import shutil
import math
from collections import Counter, deque
from pathlib import Path
from typing import Sequence

from termdash.progress import ProgressBar
from termdash.live import LiveBlock
from termdash.table import render_table
from termdash.utils import color_text as _color_text, fmt_hms, format_bytes_decimal, format_rate_bps

from .models import BatchResult, ComparisonRow, ImageResult, ScanSummary


def color_text(text: str, color: str) -> str:
    if (sys.stdout.isatty() or sys.stderr.isatty()) and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb":
        return _color_text(text, color)
    return text



def print_cache_diagnostics(report: dict, *, startup: bool = False) -> None:
    """Distinguish persistent cache dates/run lookups from per-image trial totals."""
    if startup:
        if report["file"]:
            print(
                f"Cache dates (UTC): created {report['created_at'] or 'unknown (legacy cache)'}; "
                f"last result saved {report['last_result_saved_at'] or 'none recorded'}"
            )
        return
    reasons = ", ".join(f"{name}={count}" for name, count in sorted(report["miss_reasons"].items())) or "none"
    print(
        f"Cache lookups this run: {report['lookup_hits']} hits, {report['lookup_misses']} misses ({reasons}). "
        "Includes AUTO candidate probes; not image counts."
    )


class CompresserDashboard:
    """Live in-place multi-line progress dashboard powered by TermDash concepts."""

    def __init__(
        self,
        strategy_name: str,
        total_images: int,
        *,
        mode: str = "ANALYSIS",
        enabled: bool = True,
        images: Sequence = (),
        workers: int = 4,
        stages: Sequence[str] = (),
    ) -> None:
        self.strategy_name = strategy_name
        self.total_images = max(1, total_images)
        self.mode = mode.upper()
        self.enabled = enabled
        self.block = LiveBlock(stream=sys.stderr, enabled=enabled)
        self.interactive = self.block.interactive
        self.workers = workers
        self.activity = {}
        self.start_time = time.monotonic()
        self.stage_start = self.start_time
        self.stages = tuple(stages) or (strategy_name,)
        self.stage_index = 0
        self.overall_total = self.total_images * len(self.stages)
        self.overall_processed = 0
        self.last_render = 0.0
        self.processed = 0
        self.current_savings = 0
        self.total_orig_bytes = 0
        self.last_res: ImageResult | None = None
        self.stopping = False
        self.gallery_totals = Counter(image.path.parent for image in images)
        self.gallery_done = Counter()
        self.samples = deque([(self.start_time, 0)])

        self.batch_bar = ProgressBar("batch", self.total_images, 0, width=28, charset="block")
        self.block.update(self._lines)

    def begin_stage(self, index: int) -> None:
        """Reset only stage-local counters; elapsed/overall progress stay continuous."""
        self.stage_index = index
        self.strategy_name = self.stages[index]
        self.stage_start = time.monotonic()
        self.processed = 0
        self.last_res = None
        self.current_savings = 0
        self.total_orig_bytes = 0
        self.gallery_done.clear()
        self.activity = {}
        self.batch_bar.set(0)
        if self.enabled:
            self.block.update(self._lines)

    def update(self, done_count: int, result: ImageResult) -> None:
        if not self.enabled:
            return
        self.processed = done_count
        self.overall_processed = self.stage_index * self.total_images + done_count
        self.last_res = result
        self.current_savings += result.saved_bytes
        self.total_orig_bytes += result.original_bytes
        self.batch_bar.set(done_count)
        self.gallery_done[result.input_path.parent] += 1

        now = time.monotonic()
        self.samples.append((now, self.overall_processed))
        while len(self.samples) > 1 and self.samples[0][0] < now - 15:
            self.samples.popleft()
        if not self.interactive:
            if now - self.last_render >= 5.0 or done_count == self.total_images:
                self._render_plain()
                self.last_render = now
            return

        if now - self.last_render >= 0.08 or done_count == self.total_images:
            self.block.update(self._lines)
            self.last_render = now

    def update_activity(self, event: dict) -> None:
        self.activity = event
        # LiveBlock's timer reads this immutable snapshot; phase transitions must
        # not trigger hundreds of synchronous terminal renders per second.

    def _render_plain(self) -> None:
        pct = (self.processed / self.total_images) * 100.0
        elapsed = fmt_hms(time.monotonic() - self.start_time)
        rate = self.processed / max(0.001, time.monotonic() - self.start_time)
        print(
            f"[{self.mode}] Stage {self.stage_index + 1}/{len(self.stages)} {self.strategy_name}: "
            f"{self.processed}/{self.total_images} ({pct:5.1f}%) | "
            f"Overall trials: {self.overall_processed}/{self.overall_total} | "
            f"Saved: {format_bytes_decimal(self.current_savings)} | "
            f"Rate: {rate:.1f} img/s | Elapsed: {elapsed}",
            file=sys.stderr,
            flush=True,
        )

    def _lines(self) -> list[str]:
        now = time.monotonic()
        elapsed = now - self.start_time
        rate_img = self.processed / max(0.001, now - self.stage_start)
        rate_bytes = self.total_orig_bytes / max(0.001, now - self.stage_start)

        remaining = max(0, self.overall_total - self.overall_processed)
        recent = [(stamp, done) for stamp, done in tuple(self.samples) if stamp >= now - 15]
        recent_rate = ((self.overall_processed - recent[0][1]) / max(0.001, now - recent[0][0])) if recent else 0
        eta = fmt_hms(remaining / recent_rate) if recent_rate > 0 else "unknown"

        res = self.last_res
        if res:
            fname = res.input_path.name
            orig_sz = format_bytes_decimal(res.original_bytes)
            comp_sz = format_bytes_decimal(res.compressed_bytes)
            sav_pct = f"-{res.savings_percent:.1f}%" if res.savings_percent > 0 else "0.0%"
            ssim_str = f"{res.ssim:.3f}" if res.ssim is not None else "N/A"
            file_line = (
                f"Last completed: {color_text(fname, 'bright')} ({orig_sz}) -> {res.output_path.name} "
                f"({comp_sz}, {color_text(sav_pct, 'green')}) | SSIM: {ssim_str}"
            )
            if res.error:
                file_line = f"Last completed: {fname} | FAILED: {res.error}"
            elif res.skipped:
                file_line += f" | Kept original: {res.skip_reason or 'unchanged'}"
        else:
            file_line = "Last completed: waiting for first image trial..."

        savings_pct = (
            (self.current_savings / max(1, self.total_orig_bytes)) * 100.0 if self.total_orig_bytes > 0 else 0.0
        )

        gallery = res.input_path.parent if res else None
        gallery_count = self.gallery_done[gallery] if gallery else 0
        gallery_total = self.gallery_totals.get(gallery, 0)
        gallery_bar = ProgressBar("gallery", gallery_total or 1, gallery_count, width=28, charset="block")
        gallery_bar_str = color_text(str(gallery_bar), "magenta")

        stage_bar_str = color_text(str(self.batch_bar), "cyan")

        completed_stages = self.stage_index + int(self.processed == self.total_images)
        stage_labels = []
        for index, name in enumerate(self.stages):
            state = "done" if index < completed_stages else "running" if index == self.stage_index else "pending"
            label = f"{name} ({state})"
            if self.interactive and "NO_COLOR" not in os.environ:
                label = _color_text(label, {"done": "green", "running": "blue", "pending": "yellow"}[state])
            stage_labels.append(label)

        trial_bar = ProgressBar("trial", self.overall_total, self.overall_processed, width=28, charset="block")
        trial_bar_str = color_text(str(trial_bar), "yellow")

        overall_bar = ProgressBar("overall", len(self.stages), completed_stages, width=28, charset="block")
        overall_bar_str = color_text(str(overall_bar), "green")

        phase_title = "[PHASE 2/2: EXECUTING COMPRESSION]" if self.mode == "WRITE" else "[PHASE 2/2: COMPRESSION BENCHMARK]"
        phase_badge = color_text(phase_title, "cyan")

        lines = [
            f"{phase_badge} Stages {completed_stages}/{len(self.stages)} complete: " + " | ".join(stage_labels),
            f"{color_text('Compresser', 'bright')} | Mode: {color_text('STOPPING' if self.stopping else self.mode, 'cyan')} | Strategy: {color_text(self.strategy_name, 'bright')} | Worker limit: {self.workers}",
            file_line,
            f"Stage trials: {self.processed}/{self.total_images} | Rate: {color_text(f'{rate_img:.1f} img/s', 'yellow')} ({format_rate_bps(rate_bytes)})",
            f"Elapsed (entire run): {fmt_hms(elapsed)} | Overall ETA: {color_text(eta, 'green')} (rolling rate; encoder speeds vary)",
            f"Stage savings: {color_text(format_bytes_decimal(self.current_savings), 'green')} / {format_bytes_decimal(self.total_orig_bytes)} ({savings_pct:.1f}%)",
            f"Gallery: {color_text(gallery.name if gallery else 'waiting for first completion', 'bright')}",
            f"Gallery  {gallery_bar_str} {gallery_count}/{gallery_total or '?'} (current stage)",
            f"Stage    {stage_bar_str} {self.processed}/{self.total_images}",
        ]
        if len(self.stages) > 1:
            lines.append(f"Trial    {trial_bar_str} {self.overall_processed}/{self.overall_total} image-strategy trials")
            lines.append(f"Overall  {overall_bar_str} {completed_stages}/{len(self.stages)} stages complete")
        else:
            lines.append(f"Overall  {trial_bar_str} {self.overall_processed}/{self.overall_total} image-strategy trials")

        activity = self.activity
        if activity:
            descriptions = [
                f"{color_text(Path(item['path']).name, 'bright')} ({item['width']}x{item['height']}, "
                f"{format_bytes_decimal(item['estimated_bytes'])}, {now-item['started']:.1f}s, "
                f"{item.get('phase', 'starting')})"
                for item in activity["active_images"][:2]
            ]
            eff = (
                (100.0 * activity["active_workers"] / max(1, activity["effective_workers"]))
                if activity["effective_workers"] > 0
                else 0.0
            )
            eff_color = "green" if eff >= 60 else "yellow" if eff >= 25 else "red"
            eff_str = color_text(f"{eff:.0f}%", eff_color)
            waiting = activity.get("waiting_reason") or "none"
            if waiting != "none" and self.interactive:
                waiting = color_text(f"WAIT_MEM ({waiting})", "yellow")
            else:
                waiting = color_text("none", "green")
            lines[1] = (
                f"{color_text('Compresser', 'bright')} | Mode: {color_text('STOPPING' if self.stopping else self.mode, 'cyan')} | "
                f"Strategy: {color_text(self.strategy_name, 'bright')} | Pool Efficiency: {eff_str} ({activity['active_workers']}/{activity['effective_workers']} active)"
            )
            lines[2:2] = [
                f"Workers: requested {activity['requested_workers']} | effective {activity['effective_workers']} | "
                f"active {color_text(str(activity['active_workers']), 'cyan')} | remaining {activity['remaining_images']}",
                f"Limiter: {activity['limiter']} | Budget: {color_text(format_bytes_decimal(activity['memory_budget_bytes']), 'green')} | "
                f"largest image estimate: {format_bytes_decimal(activity['largest_estimated_image_bytes'])}"
                + (" (includes oversized/rejected images)" if activity["includes_oversized_images"] else ""),
                f"Reserved: {color_text(format_bytes_decimal(activity.get('reserved_bytes', 0)), 'green')} | "
                f"Preflight rejected: {activity.get('preflight_rejected_images', 0)} | Waiting: {waiting}",
                "Active: "
                + (" | ".join(descriptions) or "none")
                + (f" | +{activity['active_workers'] - 2} more" if activity["active_workers"] > 2 else ""),
            ]
        return lines

    def close(self) -> None:
        self.block.close()

    def cancel(self, active: int) -> None:
        self.stopping = True
        self.block.log(
            f"Stopping: no new jobs; waiting for {active} active encoder(s). Native calls must return before stopping."
        )


def report_cancellation(dashboard: CompresserDashboard | None, active: int) -> None:
    if dashboard:
        dashboard.cancel(active)
    else:
        print(
            f"Stopping: no new jobs; waiting for {active} active encoder(s). Native calls must return before stopping.",
            file=sys.stderr,
            flush=True,
        )


def print_single_summary(result: BatchResult, scan: ScanSummary | None = None) -> None:
    """Print a clean, colored post-processing summary table for a single compression run."""
    headers = ["Metric", "Value"]
    rows = [
        ["Strategy", color_text(result.strategy_name, "bright")],
        ["Execution Mode", "Dry-Run (Analysis)" if result.dry_run else color_text("Applied (Write)", "green")],
        ["Total Images", str(result.total_images)],
        ["Original Storage", format_bytes_decimal(result.original_bytes)],
        ["Compressed Storage", format_bytes_decimal(result.compressed_bytes)],
        [
            "Storage Savings",
            color_text(f"{format_bytes_decimal(result.saved_bytes)} ({result.savings_percent:.1f}%)", "green"),
        ],
        ["Average SSIM", f"{result.average_ssim:.4f}" if result.average_ssim is not None else "N/A"],
        [
            "Throughput",
            f"{result.throughput_images_per_s:.1f} images/s ({format_rate_bps(result.throughput_bytes_per_s)})",
        ],
        ["Elapsed Time", fmt_hms(result.elapsed_seconds)],
        ["Files Applied", str(result.applied_count)],
        ["Files Skipped", str(result.skipped_count)],
        ["Cache Hits", str(sum(item.cache_hit for item in result.results))],
        [
            "Workers requested / effective",
            f"{result.worker_diagnostics.get('requested_workers', '?')} / "
            f"{result.worker_diagnostics.get('effective_workers', '?')} ({result.worker_diagnostics.get('limiter', 'unknown')})",
        ],
        ["Failures / Errors", color_text(str(result.failed_count), "red" if result.failed_count > 0 else "default")],
    ]

    print("\n" + color_text("Compression Batch Summary", "cyan"))
    policy = result.worker_diagnostics.get("memory_policy")
    if policy:
        rows.append(["Memory policy / resolved MiB", f"{policy['requested']} / {policy['resolved_mib']}"])
        if policy.get("available_bytes_at_start") is not None:
            rows.append(["Available RAM measured at start", format_bytes_decimal(policy["available_bytes_at_start"])])
    print(render_table(headers=headers, rows=rows, alignments=["left", "right"], style="rule"))
    timings = result.worker_diagnostics.get("phase_seconds", {})
    if timings:
        print(
            "Phase worker-seconds (exclusive; parallel workers add): "
            + ", ".join(f"{name}={seconds:.2f}s" for name, seconds in sorted(timings.items()))
        )

    if scan and scan.format_counts:
        if result.total_images < scan.total_images:
            print(
                f"Measured sample only: {result.total_images}/{scan.total_images} images. Savings above are not a whole-library estimate."
            )
        fmt_headers = ["Format", "Count", "Original Size"]
        fmt_rows = [
            [fmt, str(cnt), format_bytes_decimal(scan.format_bytes.get(fmt, 0))]
            for fmt, cnt in sorted(scan.format_counts.items())
        ]
        print("\n" + color_text("Source Image Formats Breakdown", "cyan"))
        print(render_table(headers=fmt_headers, rows=fmt_rows, alignments=["left", "right", "right"], style="rule"))


def recommend_comparison_strategies(rows: Sequence[ComparisonRow]) -> dict:
    """Rank complete same-scope evidence; unsupported rows have no fallback winner."""
    projected_scope = any(r.estimate or r.sampling for r in rows)
    ranking_scope = "whole_target_projection" if projected_scope else "measured_input_set"

    def savings(row: ComparisonRow) -> float | None:
        if row.failed_count or row.measured_images <= 0:
            return None
        if projected_scope:
            value = row.estimate.get("projected_total_saved_bytes")
            if row.estimate.get("unestimated_images", 0) or row.estimate.get("unestimated_bytes", 0):
                return None
        else:
            value = row.saved_bytes
        return value if isinstance(value, (int, float)) and math.isfinite(value) and value > 0 else None

    valid = [r for r in rows if savings(r) is not None]
    reader_friendly = {"WEBP", "JPEG", "JPG", "PNG"}

    def compatible(row: ComparisonRow) -> bool:
        return bool(row.retained_formats) and set(row.retained_formats) <= reader_friendly

    practical_candidates = [
        r
        for r in valid
        if compatible(r) and (r.mode == "lossless" or r.average_ssim is not None and r.average_ssim >= 0.98)
    ]
    # A warm/mixed cache rate measures lookups, not an encoder benchmark. Drop
    # the speed term for the entire comparison if rates aren't comparable.
    use_speed = bool(practical_candidates) and all(
        r.cache_hits == 0 and math.isfinite(r.throughput_images_per_s) and r.throughput_images_per_s > 0
        for r in practical_candidates
    )

    def _serialize(row: ComparisonRow | None, *, uses_speed: bool = False) -> dict | None:
        if row is None:
            return None
        return {
            "strategy": row.strategy_name,
            "format": row.output_format,
            "mode": row.mode,
            "quality": row.quality_display,
            "saved_bytes": row.saved_bytes,
            "savings_percent": row.savings_percent,
            "projected_total_saved_bytes": row.estimate.get("projected_total_saved_bytes"),
            "average_ssim": row.average_ssim,
            "speed_img_per_s": row.throughput_images_per_s,
            "ranking_scope": ranking_scope,
            "ranking_saved_bytes": savings(row),
            "encoder_speed_used": uses_speed,
            "reader_compatibility": (
                "conditional: sampled retained formats are JPEG/PNG/WebP; verify your reader and unsampled pages"
                if compatible(row)
                else "unverified retained formats"
            ),
            "retained_formats": list(row.retained_formats),
        }

    max_savings_row = max(
        valid,
        key=lambda r: (savings(r), r.strategy_name),
        default=None,
    )
    lossless_candidates = [r for r in valid if r.mode == "lossless"]
    best_lossless_row = max(
        lossless_candidates,
        key=lambda r: (savings(r), r.strategy_name),
        default=None,
    )

    max_rate = max((r.throughput_images_per_s for r in practical_candidates), default=1.0) or 1.0
    max_saved = max((savings(r) for r in practical_candidates), default=1)

    def _practical_score(row: ComparisonRow) -> tuple[float, float, float]:
        savings_norm = savings(row) / max_saved
        speed_norm = min(1.0, row.throughput_images_per_s / max_rate) if use_speed else 0.0
        fidelity = 1.0 if row.mode == "lossless" else row.average_ssim
        return (
            (0.55 if use_speed else 0.80) * savings_norm + 0.25 * speed_norm + 0.20 * fidelity,
            savings(row),
            speed_norm,
        )

    practical_row = max(practical_candidates, key=_practical_score, default=None)

    return {
        "maximum_savings": _serialize(max_savings_row),
        "best_lossless": _serialize(best_lossless_row),
        "practical_tradeoff": _serialize(practical_row, uses_speed=use_speed),
        "ranking_scope": ranking_scope,
        "unavailable_reason": "No eligible positive-savings evidence" if not valid else None,
        "fidelity_caveat": (
            "Recommendations separate maximum byte reduction from a practical reader-compatible "
            "speed/fidelity trade-off, using complete target projections for samples. Point-estimate rankings "
            "are not statistically proven winners. Failed/unestimated/nonpositive rows are excluded; "
            "warm-cache rates are not encoder speed. Reader compatibility is conditional on observed retained "
            "formats; real Windows terminal/reader acceptance is still manual. SSIM is an approximate structural metric, not a guarantee "
            "against visible ringing or banding on text/screentones; inspect full-resolution previews (-O) "
            "before lossy writes."
        ),
    }


def print_comparison_matrix(
    rows: Sequence[ComparisonRow],
    *,
    target_path: Path | str | None = None,
    workers: int = 4,
    runner: str = "mangadl",
) -> None:
    """Print a multi-strategy comparison table with hero recommendations and actionable command."""
    recommendations = recommend_comparison_strategies(rows)
    max_entry = recommendations.get("maximum_savings")
    tradeoff_entry = recommendations.get("practical_tradeoff")

    # 1. Recommended Hero Banner
    if max_entry:
        target_name = Path(target_path).name if target_path else "Current Target"
        sample_count = max_entry.get("sample_images", rows[0].measured_images if rows else 0)
        print("\n" + color_text("╭─ COMPRESSION BENCHMARK RESULTS ────────────────────────────────────────────────────────╮", "cyan"))
        print(f"│ Target: {target_name}  •  Evaluated: {len(rows)} Strategies on {sample_count} Sample Images   │")
        print(color_text("╰────────────────────────────────────────────────────────────────────────────────────────╯", "cyan"))
        print(f"\n  {color_text('🏆 RECOMMENDED STRATEGY', 'bright')}")
        print(f"  Strategy:    {color_text(max_entry['strategy'], 'green')} ({max_entry['format'].upper()} {max_entry['quality']})")
        ssim_val = max_entry.get("average_ssim")
        ssim_str = f"{ssim_val:.3f}" if ssim_val is not None else "N/A"
        print(f"  Perception:  SSIM {ssim_str}")
        print(f"  Projected:   Saved {format_bytes_decimal(max_entry['ranking_saved_bytes'])} ({max_entry['ranking_scope']})")
        if tradeoff_entry and tradeoff_entry["strategy"] != max_entry["strategy"]:
            t_ssim = f"{tradeoff_entry['average_ssim']:.3f}" if tradeoff_entry.get("average_ssim") is not None else "N/A"
            print(f"\n  {color_text('⚖ BEST QUALITY/SPEED BALANCE', 'bright')}")
            print(f"  Strategy:    {tradeoff_entry['strategy']} ({tradeoff_entry['format'].upper()} {tradeoff_entry['quality']}) • SSIM: {t_ssim} • Rate: {tradeoff_entry.get('speed_img_per_s', 0):.1f} img/s")

    print("\n" + color_text("Compression Strategy Comparison Matrix", "cyan"))
    cols = shutil.get_terminal_size().columns
    if cols < 100:
        # Stacked records preserve meaning without truncating labels in narrow terminals.
        for row in rows:
            print(f"\n{row.strategy_name} | {row.output_format.upper()} | {row.quality_display}")
            print(f"  Retained: {format_bytes_decimal(row.compressed_bytes)} | Savings: {row.savings_percent:.1f}%")
            print(f"  SSIM: {row.average_ssim:.3f}" if row.average_ssim is not None else "  SSIM: N/A")
            print(f"  Trials: {row.measured_images} | Rate: {row.throughput_images_per_s:.1f}/s")
            print(f"  Failures: {row.failed_count} | Kept: {row.skipped_count} | Cached: {row.cache_hits}")
    else:
        best_strat = max_entry["strategy"] if max_entry else None
        table_rows = []
        for idx, r in enumerate(rows):
            num_badge = "★" if r.strategy_name == best_strat else ("✗" if r.failed_count > 0 else str(idx + 1))
            strat_disp = color_text(r.strategy_name, "bright")
            fmt_disp = f"{r.output_format.upper()} ({r.quality_display})"
            if r.failed_count > 0 and r.measured_images == 0:
                ssim_disp = color_text("FAILED", "red")
                speed_disp = color_text("FAILED", "red")
            elif r.average_ssim is None:
                ssim_disp = "N/A"
                speed_disp = f"{r.throughput_images_per_s:.1f} img/s"
            else:
                badge = "(Loss)" if (r.average_ssim >= 0.9995 or r.mode == "lossless") else ("(✓✓)" if r.average_ssim >= 0.990 else ("(✓)" if r.average_ssim >= 0.970 else "(!)"))
                ssim_disp = f"{r.average_ssim:.3f} {badge}"
                speed_disp = f"{r.throughput_images_per_s:.1f} img/s"
            saved_disp = f"{r.savings_percent:.1f}% (-{format_bytes_decimal(r.saved_bytes)})" if r.saved_bytes > 0 else "0.0% (0 B)"
            est_bytes = r.estimate.get("projected_total_saved_bytes") if r.estimate else None
            est_disp = f"-{format_bytes_decimal(est_bytes)}" if est_bytes is not None else ("0 B" if r.saved_bytes == 0 else "N/A")
            table_rows.append([num_badge, strat_disp, fmt_disp, ssim_disp, saved_disp, est_disp, speed_disp])
        print(
            render_table(
                headers=["#", "Strategy", "Format", "SSIM Score", "Sample Saved", "Gallery Est", "Speed"],
                rows=table_rows,
                alignments=["center", "left", "left", "left", "right", "right", "right"],
                style="rule",
            )
        )
        print("  Quality Badges: (Loss) Bit-for-bit Exact • (✓✓) Imperceptible • (✓) Slight Smoothing • (✗) Failed")
        for row in rows:
            print(f"  {row.strategy_name}: Retained: {format_bytes_decimal(row.compressed_bytes)} | Savings: {row.savings_percent:.1f}% | Failures: {row.failed_count} | Kept: {row.skipped_count} | Cached: {row.cache_hits}")

    for row in rows:
        if row.estimate:
            estimate = row.estimate
            value = estimate["projected_total_saved_bytes"]
            display = format_bytes_decimal(value) if value is not None else "unavailable (failed/unmeasured galleries)"
            interval = estimate["approximate_95_percent_interval_bytes"]
            bounds = (
                (
                    f"; approximate 95% interval {format_bytes_decimal(interval[0])}.."
                    f"{format_bytes_decimal(interval[1])}"
                )
                if interval is not None
                else "; uncertainty interval unavailable"
            )
            print(f"  {row.strategy_name}: projected whole-target savings {display}{bounds}")
    if any(row.estimate for row in rows):
        print(rows[0].estimate["uncertainty"])

    print("Comparison Recommendations:")
    for label, key in (
        ("Maximum storage savings", "maximum_savings"),
        ("Best lossless (pixel-exact)", "best_lossless"),
        ("Practical speed/fidelity/reader trade-off", "practical_tradeoff"),
    ):
        entry = recommendations.get(key)
        if entry:
            ssim_txt = f"{entry['average_ssim']:.3f}" if entry["average_ssim"] is not None else "N/A"
            print(
                f"  {label}: {entry['strategy']} ({entry['format'].upper()} {entry['quality']}, "
                f"{entry['ranking_scope']}: saved {format_bytes_decimal(entry['ranking_saved_bytes'])}, "
                f"SSIM {ssim_txt}, {entry['speed_img_per_s']:.1f} img/s)"
            )
        else:
            print(f"  {label}: unavailable (no eligible positive-savings evidence)")
    print(f"  Note: {recommendations['fidelity_caveat']}")
    print("Savings use retained size: originals stay when candidates are not smaller or a trial fails.")
    print("Kept excludes failures; SSIM describes retained results, including unchanged originals.")
    print(
        "Trials count images once per strategy; AUTO may test several encoders internally. Trial rate is not successful encoding speed."
    )
    for row in rows:
        if row.worker_diagnostics:
            print(
                f"  {row.strategy_name}: workers requested {row.worker_diagnostics['requested_workers']}, "
                f"effective {row.worker_diagnostics['effective_workers']}; limiter: {row.worker_diagnostics['limiter']}."
            )
            timings = row.worker_diagnostics.get("phase_seconds", {})
            if "peak_reserved_bytes" in row.worker_diagnostics:
                print(
                    f"    Peak reserved estimate: {format_bytes_decimal(row.worker_diagnostics['peak_reserved_bytes'])}; "
                    f"preflight rejected: {row.worker_diagnostics.get('preflight_rejected_images', 0)}; "
                    f"accumulated dispatch wait: {row.worker_diagnostics.get('dispatch_wait_seconds', 0):.2f} task-seconds."
                )
            if timings:
                print(
                    "    Phase worker-seconds (exclusive; parallel workers add): "
                    + ", ".join(f"{phase}={seconds:.2f}s" for phase, seconds in sorted(timings.items()))
                )
            scratch = row.worker_diagnostics.get("scratch")
            if scratch:
                print(
                    f"    Scratch staging: {scratch['staged_files']} staged, {scratch['reused_files']} reused, "
                    f"{format_bytes_decimal(scratch['bytes_copied'])} copied in {scratch['copy_seconds']:.2f}s."
                )
        if row.candidate_bytes is not None and row.original_bytes:
            change = (row.candidate_bytes / row.original_bytes - 1) * 100
            print(
                f"  {row.strategy_name}: encoded candidates {format_bytes_decimal(row.candidate_bytes)} "
                f"({change:+.1f}% vs original; before retaining larger originals)."
            )
        for reason in row.error_summary:
            print(f"  {row.strategy_name}: {reason}")

    # 3. Actionable Command Prompt
    if max_entry and target_path:
        strat_name = max_entry["strategy"]
        fmt = max_entry["format"]
        quality = max_entry.get("quality", "")
        mode = "lossy" if "lossy" in strat_name or "q=" in quality else "lossless"
        q_flag = f"-q {quality.replace('q=', '')} " if mode == "lossy" and "q=" in quality else ""
        target_str = str(target_path)
        if runner == "mangadl":
            cmd = f"mangadl compress -d '{target_str}' -f {fmt} -m {mode} {q_flag}-B auto -t {workers} -w"
        else:
            cmd = f"compresser -i '{target_str}' -f {fmt} -m {mode} {q_flag}-B auto -t {workers} -w"
        width = max(len(cmd) + 6, 78)
        h_line = "─" * (width - 2)
        print("\n" + color_text(f"╭─ READY TO COMPRESS? {h_line[21:]}╮", "green"))
        print(f"│ To apply the recommended strategy ({strat_name}) to this target, run:".ljust(width - 1) + "│")
        print("│" + " " * (width - 2) + "│")
        print(f"│   {cmd}".ljust(width - 1) + "│")
        print(color_text(f"╰{h_line}╯", "green"))
