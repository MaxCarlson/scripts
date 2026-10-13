#!/usr/bin/env python3
"""
TermDash UI integration, live in-place progress, and post-processing reports.
"""

from __future__ import annotations

import os
import sys
import time
from collections import Counter, deque
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
    ) -> None:
        self.strategy_name = strategy_name
        self.total_images = max(1, total_images)
        self.mode = mode.upper()
        self.enabled = enabled
        self.block = LiveBlock(stream=sys.stderr, enabled=enabled)
        self.interactive = self.block.interactive
        self.workers = workers
        self.start_time = time.monotonic()
        self.last_render = 0.0
        self.processed = 0
        self.current_savings = 0
        self.total_orig_bytes = 0
        self.last_res: ImageResult | None = None
        self.gallery_totals = Counter(image.path.parent for image in images)
        self.gallery_done = Counter()
        self.samples = deque([(self.start_time, 0)])

        self.batch_bar = ProgressBar("batch", self.total_images, 0, width=28, charset="block")
        self.block.update(self._lines)

    def update(self, done_count: int, result: ImageResult) -> None:
        if not self.enabled:
            return
        self.processed = done_count
        self.last_res = result
        self.current_savings += result.saved_bytes
        self.total_orig_bytes += result.original_bytes
        self.batch_bar.set(done_count)
        self.gallery_done[result.input_path.parent] += 1

        now = time.monotonic()
        self.samples.append((now, done_count))
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

    def _render_plain(self) -> None:
        pct = (self.processed / self.total_images) * 100.0
        elapsed = fmt_hms(time.monotonic() - self.start_time)
        rate = self.processed / max(0.001, time.monotonic() - self.start_time)
        print(
            f"[{self.mode}] {self.processed}/{self.total_images} ({pct:5.1f}%) | "
            f"Saved: {format_bytes_decimal(self.current_savings)} | "
            f"Rate: {rate:.1f} img/s | Elapsed: {elapsed}",
            file=sys.stderr,
            flush=True,
        )

    def _lines(self) -> list[str]:
        now = time.monotonic()
        elapsed = now - self.start_time
        rate_img = self.processed / max(0.001, elapsed)
        rate_bytes = self.total_orig_bytes / max(0.001, elapsed)

        remaining = max(0, self.total_images - self.processed)
        recent = [(stamp, done) for stamp, done in tuple(self.samples) if stamp >= now - 15]
        recent_rate = ((self.processed - recent[0][1]) / max(0.001, now - recent[0][0])) if recent else 0
        eta = fmt_hms(remaining / recent_rate) if recent_rate > 0 else "unknown"

        mode_color = "yellow" if self.mode == "ANALYSIS" else "green"

        res = self.last_res
        if res:
            fname = res.input_path.name
            orig_sz = format_bytes_decimal(res.original_bytes)
            comp_sz = format_bytes_decimal(res.compressed_bytes)
            sav_pct = f"-{res.savings_percent:.1f}%" if res.savings_percent > 0 else "0.0%"
            ssim_str = f"{res.ssim:.3f}" if res.ssim is not None else "N/A"
            file_line = (
                f"File: {color_text(fname, 'bright')} ({orig_sz}) -> {res.output_path.name} "
                f"({comp_sz}, {color_text(sav_pct, 'green')}) | SSIM: {ssim_str}"
            )
        else:
            file_line = "File: Initializing..."

        savings_pct = (
            (self.current_savings / max(1, self.total_orig_bytes)) * 100.0 if self.total_orig_bytes > 0 else 0.0
        )

        gallery = res.input_path.parent if res else None
        gallery_count = self.gallery_done[gallery] if gallery else 0
        gallery_total = self.gallery_totals.get(gallery, 0)
        gallery_bar = ProgressBar("gallery", gallery_total or 1, gallery_count, width=28, charset="block")
        return [
            f"{color_text('Compresser', 'bright')} | Mode: {color_text(self.mode, mode_color)} | Strategy: {self.strategy_name} | Worker limit: {self.workers}",
            file_line,
            f"Processed: {self.processed}/{self.total_images} | Rate: {rate_img:.1f} img/s ({format_rate_bps(rate_bytes)}) | Elapsed: {fmt_hms(elapsed)} | ETA: {eta}",
            f"Current Savings: {color_text(format_bytes_decimal(self.current_savings), 'green')} / {format_bytes_decimal(self.total_orig_bytes)} ({savings_pct:.1f}%)",
            f"Gallery: {gallery.name if gallery else 'waiting for first completion'} {gallery_bar} {gallery_count}/{gallery_total or '?'}",
            f"Batch: {self.batch_bar}",
        ]

    def close(self) -> None:
        self.block.close()


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
        ["Failures / Errors", color_text(str(result.failed_count), "red" if result.failed_count > 0 else "default")],
    ]

    print("\n" + color_text("Compression Batch Summary", "cyan"))
    print(render_table(headers=headers, rows=rows, alignments=["left", "right"], style="rule"))

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
        "Total Size",
        "Savings %",
        "Avg SSIM",
        "Speed",
        "Relative Storage Savings",
        "Failures",
        "Cached",
    ]

    table_rows = []
    max_savings = max((r.savings_percent for r in rows), default=1.0)

    for r in rows:
        ratio = (r.savings_percent / 100.0) if max_savings > 0 else 0.0
        bar = render_horizontal_bar(ratio, width=16, color="green", show_pct=False)
        table_rows.append(
            [
                color_text(r.strategy_name, "bright"),
                r.output_format.upper(),
                r.mode,
                r.quality_display,
                format_bytes_decimal(r.compressed_bytes),
                color_text(f"-{r.savings_percent:.1f}%", "green") if r.savings_percent > 0 else "0.0%",
                f"{r.average_ssim:.3f}" if r.average_ssim is not None else "N/A",
                f"{r.throughput_images_per_s:.1f} img/s",
                f"{bar} {r.savings_percent:4.1f}%",
                str(r.failed_count),
                str(r.cache_hits),
            ]
        )

    print("\n" + color_text("Compression Strategy Comparison Matrix", "cyan"))
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
            ],
            style="rule",
        )
    )
