#!/usr/bin/env python3
"""
TermDash UI integration, live in-place progress, and post-processing reports.
"""

from __future__ import annotations

import os
import sys
import time
import shutil
from collections import Counter, deque
from pathlib import Path
from typing import Sequence

from termdash.progress import ProgressBar, render_horizontal_bar
from termdash.live import LiveBlock
from termdash.table import render_table
from termdash.utils import color_text as _color_text, fmt_hms, format_bytes_decimal, format_rate_bps

from .models import BatchResult, ComparisonRow, ImageResult, ScanSummary


def color_text(text: str, color: str) -> str:
    if sys.stdout.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb":
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
        stage_labels = []
        completed_stages = self.stage_index + int(self.processed == self.total_images)
        for index, name in enumerate(self.stages):
            state = "done" if index < completed_stages else "running" if index == self.stage_index else "pending"
            label = f"{name} ({state})"
            if self.interactive and "NO_COLOR" not in os.environ:
                label = _color_text(label, {"done": "green", "running": "blue", "pending": "yellow"}[state])
            stage_labels.append(label)
        overall_bar = ProgressBar("overall", self.overall_total, self.overall_processed, width=28, charset="block")
        lines = [
            f"Stages {completed_stages}/{len(self.stages)} complete: " + " | ".join(stage_labels),
            f"{color_text('Compresser', 'bright')} | Mode: {'STOPPING' if self.stopping else self.mode} | Strategy: {self.strategy_name} | Worker limit: {self.workers}",
            file_line,
            f"Stage trials: {self.processed}/{self.total_images} | Rate: {rate_img:.1f} img/s ({format_rate_bps(rate_bytes)})",
            f"Elapsed (entire run): {fmt_hms(elapsed)} | Overall ETA: {eta} (rolling rate; encoder speeds vary)",
            f"Stage savings: {color_text(format_bytes_decimal(self.current_savings), 'green')} / {format_bytes_decimal(self.total_orig_bytes)} ({savings_pct:.1f}%)",
            f"Gallery: {gallery.name if gallery else 'waiting for first completion'}",
            f"Gallery  {gallery_bar} {gallery_count}/{gallery_total or '?'} (current stage)",
            f"Stage    {self.batch_bar} {self.processed}/{self.total_images}",
            f"Overall  {overall_bar} {self.overall_processed}/{self.overall_total} image-strategy trials",
        ]
        activity = self.activity
        if activity:
            descriptions = [
                f"{Path(item['path']).name} ({item['width']}x{item['height']}, "
                f"{format_bytes_decimal(item['estimated_bytes'])} estimated, {now-item['started']:.1f}s, "
                f"{item.get('phase', 'starting')})"
                for item in activity["active_images"][:2]
            ]
            lines[1] = (
                f"Compresser | Mode: {'STOPPING' if self.stopping else self.mode} | Strategy: {self.strategy_name}"
            )
            lines[2:2] = [
                f"Workers: requested {activity['requested_workers']} | effective {activity['effective_workers']} | "
                f"active {activity['active_workers']} | remaining {activity['remaining_images']}",
                f"Limiter: {activity['limiter']} | Budget: {format_bytes_decimal(activity['memory_budget_bytes'])} | "
                f"largest image estimate: {format_bytes_decimal(activity['largest_estimated_image_bytes'])}"
                + (" (includes oversized/rejected images)" if activity["includes_oversized_images"] else ""),
                f"Reserved: {format_bytes_decimal(activity.get('reserved_bytes', 0))} | "
                f"Preflight rejected: {activity.get('preflight_rejected_images', 0)}",
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


def print_comparison_matrix(rows: Sequence[ComparisonRow]) -> None:
    """Print a multi-strategy comparison table with horizontal visual comparison bars."""
    headers = [
        "Strategy",
        "Format",
        "Mode",
        "Quality",
        "Retained Size",
        "Savings %",
        "Avg SSIM",
        "Trial Rate",
        "Relative Storage Savings",
        "Failures",
        "Kept",
        "Cached",
        "Projected Saved",
    ]

    table_rows = []
    max_savings = max((r.savings_percent for r in rows), default=1.0)

    for r in rows:
        ratio = (r.savings_percent / 100.0) if max_savings > 0 else 0.0
        bar = color_text(render_horizontal_bar(ratio, width=16, show_pct=False), "green")
        table_rows.append(
            [
                color_text(r.strategy_name, "bright"),
                r.output_format.upper(),
                r.mode,
                r.quality_display,
                format_bytes_decimal(r.compressed_bytes),
                color_text(f"{r.savings_percent:.1f}%", "green") if r.savings_percent > 0 else "0.0%",
                f"{r.average_ssim:.3f}" if r.average_ssim is not None else "N/A",
                f"{r.throughput_images_per_s:.1f} img/s",
                f"{bar} {r.savings_percent:4.1f}%",
                str(r.failed_count),
                str(r.skipped_count),
                str(r.cache_hits),
                (
                    format_bytes_decimal(r.estimate["projected_total_saved_bytes"])
                    if r.estimate.get("projected_total_saved_bytes") is not None
                    else "N/A"
                ),
            ]
        )

    print("\n" + color_text("Compression Strategy Comparison Matrix", "cyan"))
    if shutil.get_terminal_size().columns < 150:
        # Stacked records preserve meaning instead of squeezing twelve columns
        # into labels like 'Ret…' and unrecognizable strategy names.
        for row in rows:
            print(f"\n{row.strategy_name} | {row.output_format.upper()} | {row.quality_display}")
            print(f"  Retained: {format_bytes_decimal(row.compressed_bytes)} | Savings: {row.savings_percent:.1f}%")
            print(f"  SSIM: {row.average_ssim:.3f}" if row.average_ssim is not None else "  SSIM: N/A")
            print(f"  Trials: {row.measured_images} | Rate: {row.throughput_images_per_s:.1f}/s")
            print(f"  Failures: {row.failed_count} | Kept: {row.skipped_count} | Cached: {row.cache_hits}")
    else:
        print(
            render_table(
                headers=headers,
                rows=table_rows,
                alignments=[
                    "left",
                    "center",
                    "center",
                    "center",
                    "right",
                    "right",
                    "right",
                    "right",
                    "left",
                    "right",
                    "right",
                    "right",
                    "right",
                ],
                style="rule",
            )
        )
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
        if row.candidate_bytes is not None and row.original_bytes:
            change = (row.candidate_bytes / row.original_bytes - 1) * 100
            print(
                f"  {row.strategy_name}: encoded candidates {format_bytes_decimal(row.candidate_bytes)} "
                f"({change:+.1f}% vs original; before retaining larger originals)."
            )
        for reason in row.error_summary:
            print(f"  {row.strategy_name}: {reason}")
