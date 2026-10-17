#!/usr/bin/env python3
"""
Command-line interface for the standalone compresser module.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from .engine import CompressionEngine
from .cache import AnalysisCache
from .models import (
    ComparisonRow,
    CompressionStrategy,
    ImageMetadata,
)
from .scanner import scan_directory
from .sampling import add_analysis_arguments, validate_analysis_arguments, gallery_sample, print_sampling
from .ui import CompresserDashboard, print_comparison_matrix, print_single_summary, report_cancellation

__version__ = "0.9.0"


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with short and long flags for every option."""
    parser = argparse.ArgumentParser(
        prog="compresser",
        description="Analyze, compare, and optimize manga/manhwa images using perceptual compression.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "-R", "--recover", action="store_true", help="Preview recovery in one exact input directory; -w applies."
    )
    parser.add_argument("-C", "--confirm-recovery", help="Exact recovery preview token required with -R -w.")
    parser.add_argument(
        "-A",
        "--algorithm",
        choices=("auto", "pillow-jpeg", "pillow-webp", "pillow-png", "pillow-avif", "cli-jpegtran"),
        default="auto",
        help="Select a verified encoder (default: auto).",
    )
    parser.add_argument(
        "-e", "--effort", type=int, choices=range(7), default=6, help="PNG/WebP encoding effort 0..6 (default: 6)."
    )
    parser.add_argument(
        "-K", "--cache-file", type=Path, help="Optional persistent analysis cache outside the input directory."
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        required=True,
        help="Input image file or directory containing manga/manhwa images.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        help="Reserved; separate output mode is currently rejected.",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("auto", "webp", "jpeg", "avif", "png", "keep"),
        default="auto",
        help="Target image format (default: auto).",
    )
    parser.add_argument(
        "-m",
        "--mode",
        choices=("perceptual", "lossless", "lossy"),
        default="lossless",
        help="Compression mode (default: lossless).",
    )
    parser.add_argument(
        "-q",
        "--quality",
        type=int,
        default=80,
        help="Compression quality 1..100 (for lossy mode, default: 80).",
    )
    parser.add_argument(
        "-p",
        "--perceptual-target",
        type=float,
        default=0.990,
        help="Minimum SSIM quality threshold 0.80..1.00 (default: 0.990).",
    )
    parser.add_argument(
        "-c",
        "--compare",
        action="store_true",
        help="Run comparison matrix across multiple strategies without modifying files.",
    )
    parser.add_argument(
        "-s",
        "--sample",
        type=int,
        help="Benchmark only a representative sample of N images.",
    )
    parser.add_argument(
        "-w",
        "--write",
        action="store_true",
        help="Apply compression and write changes to disk (default: dry-run analysis).",
    )
    parser.add_argument(
        "-F",
        "--allow-larger",
        action="store_true",
        help="Permit replacement if the compressed file is larger (default: False).",
    )
    parser.add_argument(
        "-L",
        "--allow-lossy",
        action="store_true",
        help="Explicitly permit lossy compression in write mode.",
    )
    parser.add_argument(
        "-t",
        "--threads",
        type=int,
        default=max(1, min(4, os.cpu_count() or 4)),
        help="Worker thread concurrency (default: CPU budget or 4).",
    )
    parser.add_argument(
        "-N",
        "--no-ui",
        action="store_true",
        help="Disable the live terminal dashboard.",
    )
    parser.add_argument(
        "-B",
        "--memory-budget-mib",
        type=int,
        default=512,
        help="Aggregate scheduling allowance64..4096MiB; per-image decode limit stays512MiB.",
    )
    parser.add_argument(
        "-J",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON results to stdout.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase diagnostic logging output.",
    )
    add_analysis_arguments(parser)
    return parser


def run_comparison(
    images: Sequence[ImageMetadata],
    engine: CompressionEngine,
    *,
    threads: int = 4,
    no_ui: bool = False,
    mode: str = "lossless",
    quality: int = 80,
    perceptual_target: float = 0.990,
    encoder: str = "auto",
    effort: int = 6,
    compare_both: bool = False,
    sampling_plan=None,
) -> list[ComparisonRow]:
    """Execute benchmarks across standard competing compression configurations."""
    formats = ["png", "webp", "jpeg", "auto"]
    candidate_strategies = [
        CompressionStrategy(
            name=f"{fmt}-{'lossless' if fmt == 'png' else selected_mode}",
            format=fmt,
            mode="lossless" if fmt == "png" else selected_mode,
            quality=quality,
            perceptual_target=perceptual_target,
            encoder=encoder,
            method=effort,
        )
        for selected_mode in (["lossless", "lossy"] if compare_both else [mode])
        for fmt in formats
        if not (compare_both and selected_mode == "lossy" and fmt == "png")
    ]

    from collections import Counter

    rows: list[ComparisonRow] = []
    dash = (
        CompresserDashboard(
            candidate_strategies[0].name,
            len(images),
            mode="COMPARE",
            images=images,
            workers=threads,
            stages=[strategy.name for strategy in candidate_strategies],
        )
        if not no_ui
        else None
    )

    def cb(done: int, total: int, result: Any) -> None:
        if dash:
            dash.update(done, result)

    try:
        for index, strat in enumerate(candidate_strategies):
            if dash:
                dash.begin_stage(index)
            res = engine.compress_batch(
                images,
                strat,
                write_mode=False,
                threads=threads,
                progress_callback=cb,
                cancellation_callback=lambda active: report_cancellation(dash, active),
                activity_callback=dash.update_activity if dash else None,
            )
            q_disp = (
                f"SSIM>={strat.perceptual_target:.3f}"
                if strat.mode == "perceptual"
                else (f"q={strat.quality}" if strat.mode == "lossy" else "lossless")
            )
            errors = Counter(item.error for item in res.results if item.error)
            rows.append(
                ComparisonRow(
                    strategy_name=strat.name,
                    output_format=strat.format,
                    mode=strat.mode,
                    quality_display=q_disp,
                    compressed_bytes=res.compressed_bytes,
                    saved_bytes=res.saved_bytes,
                    savings_percent=res.savings_percent,
                    average_ssim=res.average_ssim,
                    throughput_images_per_s=res.throughput_images_per_s,
                    measured_images=res.processed_images,
                    failed_count=res.failed_count,
                    skipped_count=res.skipped_count,
                    cache_hits=sum(item.cache_hit for item in res.results),
                    error_summary=tuple(f"{count} failed: {reason}" for reason, count in errors.most_common(3)),
                    candidate_bytes=(
                        sum(item.candidate_bytes for item in res.results)
                        if all(item.candidate_bytes is not None for item in res.results)
                        else None
                    ),
                    original_bytes=res.original_bytes,
                    worker_diagnostics=res.worker_diagnostics,
                    sampling=sampling_plan.summary() if sampling_plan else {},
                    estimate=sampling_plan.estimate(res.results) if sampling_plan else {},
                )
            )
    finally:
        if dash:
            dash.close()
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_analysis_arguments(args)
    except ValueError as exc:
        parser.error(str(exc))
    if args.confirm_recovery and not args.recover:
        parser.error("--confirm-recovery requires --recover")
    if args.recover and (args.compare or args.sample):
        parser.error("Recovery requires one exact directory, without compare/sample selection")
    if args.output_dir is not None:
        parser.error("Separate output directories are not implemented; omit --output-dir")
    if not 1 <= args.quality <= 100 or not 0.80 <= args.perceptual_target <= 1.0:
        parser.error("Quality must be 1..100 and perceptual target 0.80..1.00")
    if args.threads < 1 or args.sample is not None and args.sample < 1:
        parser.error("Threads and sample must be positive")
    if not 64 <= args.memory_budget_mib <= 4096:
        parser.error("Aggregate scheduling budget must be64..4096MiB")
    if args.write and args.compare:
        parser.error("Comparison is read-only; omit --write")
    if args.write and not args.recover and args.mode != "lossless" and not args.allow_lossy:
        parser.error("Lossy/perceptual writes require --allow-lossy")

    try:
        if args.recover:
            from .recovery import run_recovery

            return run_recovery(args.input, apply=args.write, confirmation=args.confirm_recovery, as_json=args.json)
        if args.cache_file and (
            args.cache_file.resolve() == args.input.resolve()
            or args.input.resolve() in args.cache_file.resolve().parents
        ):
            raise ValueError("Analysis cache must be outside the input tree")
        cache = AnalysisCache(path=args.cache_file)
        summary, images = scan_directory(args.input, recursive=True, cache=cache)
        if not images:
            if args.json:
                print(json.dumps({"error": "No image files found in target path"}))
            else:
                print(f"No image files found in target: {args.input}", file=sys.stderr)
            return 1

        # Handle sample selection
        sampling_plan = gallery_sample(
            images, args.input, sample_size=args.sample, percent=args.sample_percent, seed=args.sample_seed
        )
        eval_images = sampling_plan.images
        if not args.json:
            print_sampling(sampling_plan)
        engine = CompressionEngine(cache=cache, memory_budget_bytes=args.memory_budget_mib * 1024**2)

        if args.compare:
            comp_rows = run_comparison(
                eval_images,
                engine,
                threads=args.threads,
                no_ui=args.no_ui or args.json,
                mode=args.mode,
                quality=args.quality,
                perceptual_target=args.perceptual_target,
                encoder=args.algorithm,
                effort=args.effort,
                compare_both=args.compare_both,
                sampling_plan=sampling_plan,
            )
            if args.json:
                data = [
                    {
                        "strategy": r.strategy_name,
                        "format": r.output_format,
                        "mode": r.mode,
                        "quality": r.quality_display,
                        "compressed_bytes": r.compressed_bytes,
                        "saved_bytes": r.saved_bytes,
                        "savings_percent": r.savings_percent,
                        "average_ssim": r.average_ssim,
                        "speed_img_per_s": r.throughput_images_per_s,
                        "measured_images": r.measured_images,
                        "failed_count": r.failed_count,
                        "skipped_count": r.skipped_count,
                        "cache_hits": r.cache_hits,
                        "error_summary": r.error_summary,
                        "candidate_bytes": r.candidate_bytes,
                        "original_bytes": r.original_bytes,
                        "worker_diagnostics": r.worker_diagnostics,
                        "sampling": r.sampling,
                        "estimate": r.estimate,
                    }
                    for r in comp_rows
                ]
                print(json.dumps(data, indent=2))
            else:
                print_comparison_matrix(comp_rows)
            return 0

        # Single Strategy Execution
        strat = CompressionStrategy(
            name=f"{args.format}-{args.mode}",
            format=args.format,
            mode=args.mode,
            quality=args.quality,
            perceptual_target=args.perceptual_target,
            allow_larger=args.allow_larger,
            allow_lossy=args.allow_lossy,
            encoder=args.algorithm,
            method=args.effort,
        )

        dash = None
        if not args.no_ui and not args.json:
            dash = CompresserDashboard(
                strat.name,
                len(eval_images),
                mode="WRITE" if args.write else "ANALYSIS",
                enabled=True,
                images=eval_images,
                workers=args.threads,
            )

        def cb(done: int, total: int, res: Any) -> None:
            if dash:
                dash.update(done, res)

        try:
            batch_result = engine.compress_batch(
                eval_images,
                strat,
                write_mode=args.write,
                threads=args.threads,
                progress_callback=cb,
                cancellation_callback=lambda active: report_cancellation(dash, active),
                activity_callback=dash.update_activity if dash else None,
            )
        finally:
            if dash:
                dash.close()

        if args.json:
            out = {
                "strategy": batch_result.strategy_name,
                "dry_run": batch_result.dry_run,
                "total_images": batch_result.total_images,
                "original_bytes": batch_result.original_bytes,
                "compressed_bytes": batch_result.compressed_bytes,
                "saved_bytes": batch_result.saved_bytes,
                "savings_percent": batch_result.savings_percent,
                "average_ssim": batch_result.average_ssim,
                "elapsed_seconds": batch_result.elapsed_seconds,
                "applied_count": batch_result.applied_count,
                "skipped_count": batch_result.skipped_count,
                "failed_count": batch_result.failed_count,
                "cache_hits": sum(item.cache_hit for item in batch_result.results),
                "worker_diagnostics": batch_result.worker_diagnostics,
                "scope": "sample" if len(eval_images) < summary.total_images else "full",
                "inventory_images": summary.total_images,
                "inventory_bytes": summary.total_bytes,
                "estimate": sampling_plan.estimate(batch_result.results),
                "sampling": sampling_plan.summary(),
            }
            print(json.dumps(out, indent=2))
        else:
            print_single_summary(batch_result, scan=summary)
            estimate = sampling_plan.estimate(batch_result.results)
            if estimate["scope"] != "full":
                print(
                    f"Projected savings for covered strata: {estimate['projected_covered_saved_bytes']:,} bytes; "
                    f"{estimate['unestimated_images']} images remain unestimated."
                )
                print(estimate["uncertainty"])

        return 0 if batch_result.failed_count == 0 else 1

    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    except Exception as exc:
        if args.verbose:
            import traceback

            traceback.print_exc()
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
