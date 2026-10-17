#!/usr/bin/env python3
"""
Command-line interface for the standalone compresser module.
"""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable, Sequence

from .engine import CompressionEngine
from .report_session import report_operation, start_session, current_session
from .cache import create_analysis_cache
from .inventory import InventoryStore, inventory_path, inventory_report
from .inventory_ui import emit_inventory_report
from .snapshots import SelectionSnapshot, summarize_images
from .models import (
    ComparisonRow,
    CompressionStrategy,
    ImageMetadata,
)
from .scanner import scan_directory
from .memory_policy import configure_memory_arguments
from .timing import configure_pipeline, pipeline_report, profile_pipeline
from .sampling import validate_analysis_arguments, gallery_sample
from .ui import (
    CompresserDashboard,
    recommend_comparison_strategies,
    report_cancellation,
)

__version__ = "2.0.0"


def build_parser() -> argparse.ArgumentParser:
    """Build the standalone operation-oriented command tree."""
    from .arguments import build_operation_parsers

    parser = argparse.ArgumentParser(prog="compresser", description="Measure and manage image compression.")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    build_operation_parsers(parser, owner="compresser")
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
    qualities: Sequence[int] | None = None,
    recipe_specs: Sequence[Any] | None = None,
    source_validator: Callable[[list[ImageMetadata]], None] | None = None,
    scratch_dir: Path | None = None,
) -> list[ComparisonRow]:
    """Execute benchmarks across standard competing compression configurations."""
    formats = ["png", "webp", "jpeg", "auto"]
    quality_values = list(dict.fromkeys(qualities)) if qualities is not None else [quality]
    if not quality_values or any(
        isinstance(q, bool) or not isinstance(q, int) or not 1 <= q <= 100 for q in quality_values
    ):
        raise ValueError("Comparison qualities must be integers1..100")
    if qualities is not None and not compare_both and mode != "lossy":
        raise ValueError("Multiple quality comparison requires lossy mode or compare_both")
    candidate_strategies = (
        [
            CompressionStrategy(
                name=f"{spec.format}-{spec.mode}"
                + (f"-q{spec.quality}" if spec.quality is not None else ""),
                format=spec.format,
                mode=spec.mode,
                quality=spec.quality if spec.quality is not None else quality,
                perceptual_target=spec.perceptual_target,
                encoder=spec.encoder,
                method=spec.effort,
            )
            for spec in recipe_specs
        ]
        if recipe_specs is not None
        else [
        CompressionStrategy(
            name=f"{fmt}-{'lossless' if fmt == 'png' else selected_mode}"
            + (f"-q{trial_quality}" if selected_mode == "lossy" and fmt != "png" and len(quality_values) > 1 else ""),
            format=fmt,
            mode="lossless" if fmt == "png" else selected_mode,
            quality=trial_quality,
            perceptual_target=perceptual_target,
            encoder=encoder,
            method=effort,
        )
        for selected_mode in (["lossless", "lossy"] if compare_both else [mode])
        for quality_index, trial_quality in enumerate(quality_values if selected_mode == "lossy" else [quality])
        for fmt in formats
        if not (compare_both and selected_mode == "lossy" and fmt == "png")
        and not (selected_mode == "lossy" and quality_index > 0 and fmt == "png")
        ]
    )

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
            if source_validator:
                source_validator(images)
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
                scratch_dir=scratch_dir,
            )
            q_disp = (
                f"SSIM>={strat.perceptual_target:.3f}"
                if strat.mode == "perceptual"
                else (f"q={strat.quality}" if strat.mode == "lossy" else "lossless")
            )
            errors = Counter(item.error for item in res.results if item.error)
            from dataclasses import asdict
            from .extrapolation import extrapolate_target

            population = (
                [image for group in sampling_plan.groups.values() for image in group] if sampling_plan else images
            )
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
                    issues=dict(errors),
                    settings={**asdict(strat), "elapsed_seconds": res.elapsed_seconds},
                    extrapolation=extrapolate_target(
                        population, images, res.results, complete=res.processed_images == len(images)
                    ),
                    candidate_bytes=(
                        sum(item.candidate_bytes for item in res.results)
                        if all(item.candidate_bytes is not None for item in res.results)
                        else None
                    ),
                    original_bytes=res.original_bytes,
                    worker_diagnostics=res.worker_diagnostics,
                    sampling=sampling_plan.summary() if sampling_plan else {},
                    estimate=sampling_plan.estimate(res.results) if sampling_plan else {},
                    retained_formats=tuple(
                        sorted({item.output_format.upper() for item in res.results if not item.error})
                    ),
                )
            )
    finally:
        if dash:
            dash.close()
    return rows


@report_operation
@profile_pipeline
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parsed = parser.parse_args(argv)
    if not getattr(parsed, "operation", None):
        parser.print_help()
        return 0
    from .arguments import normalize_compression_arguments

    try:
        options = normalize_compression_arguments(parsed)
    except ValueError as exc:
        parser.error(str(exc))
    if options.operation == "estimate":
        parser.error("The estimate workflow is not available yet; use plan to prepare a bounded design")
    args = options.legacy_namespace(parsed)
    from .workspace import configure_workspace

    try:
        if not args.recover:
            configure_workspace(args, args.input, owner="compresser")
    except (OSError, ValueError) as exc:
        print(f"Error in compresser: {exc}", file=sys.stderr)
        return 2
    try:
        configure_memory_arguments(args)
    except ValueError as exc:
        parser.error(str(exc))
    configure_pipeline(
        requested_workers=args.threads,
        inventory_effective_workers=1,
        memory_budget_mib=args.memory_budget_mib,
        memory_policy=args._memory_policy.diagnostics(),
        cache_policy=args.cache_policy,
        inventory_policy=args.inventory_policy,
        inventory_depth=args.inventory_depth,
        mode=args.mode,
        effort=args.effort,
    )
    try:
        validate_analysis_arguments(args)
    except ValueError as exc:
        parser.error(str(exc))
    if hasattr(args, "input") and args.input:
        args.input = Path(str(args.input).rstrip("/\\")).resolve()
    if args.confirm_recovery and not args.recover:
        parser.error("--confirm-recovery requires --recover")
    if args.recover and (args.compare or args.sample):
        parser.error("Recovery requires one exact directory, without compare/sample selection")
    if args.output_dir is not None:
        parser.error("Separate output directories are not implemented; omit --output-dir")
    if not 1 <= args.quality <= 100 or not 0.80 <= args.perceptual_target <= 1.0:
        parser.error("Quality must be 1..100 and perceptual target 0.80..1.00")
    if args.threads < 1 or args.sample is not None and args.sample != "auto" and args.sample < 1:
        parser.error("Threads and sample must be positive")
    if args.memory_budget_mib < 64:
        parser.error("Aggregate scheduling budget must be at least 64MiB")
    if args.write and args.compare:
        parser.error("Comparison is read-only; omit --write")
    if args.write and not args.recover and args.mode != "lossless" and not args.allow_lossy:
        parser.error("Lossy/perceptual writes require --allow-lossy")

    cache = None
    resources = ExitStack()
    try:
        if args.recover:
            from .recovery import run_recovery

            return run_recovery(args.input, apply=args.write, confirmation=args.confirm_recovery, as_json=args.json)
        from .inventory_ui import InventoryProgress
        from cross_platform.locks import folder_read_lock, folder_write_lock

        operation_guard = nullcontext()
        if args.input.expanduser().exists():
            if args.write:
                root = args.input if args.input.is_dir() else args.input.parent
                operation_guard = folder_write_lock(root, operation="compresser -w")
            else:
                operation_guard = folder_read_lock(
                    args.input,
                    operation=(f"compresser -l -D {args.inventory_depth}" if args.inventory_only else "compresser"),
                )
        resources.enter_context(operation_guard)
        from .workspace import initialize_workspace

        if not args.input.exists():
            raise ValueError(f"Compression target does not exist: {args.input}")
        initialize_workspace(args._workspace)
        session = start_session(args)
        if options.operation == "plan":
            from .sampling_plan import execute_plan_operation

            return execute_plan_operation(args, options, owner="compresser")
        # Keep ownership in resources through discovery and the final encoder trial.
        with nullcontext():
            if args.inventory_only and args.inventory_depth == "files":
                from .file_inventory import scan_file_inventory

                prog = InventoryProgress(args.input, depth="files", enabled=not args.no_ui and not args.json)
                try:
                    report = scan_file_inventory(
                        args.input, inventory_path(args, args.input), progress=prog, threads=args.threads
                    )
                finally:
                    prog.close()
                emit_inventory_report(report, as_json=args.json)
                return 0
            if args.cache_file and (
                args.cache_file.resolve() == args.input.resolve()
                or args.input.resolve() in args.cache_file.resolve().parents
            ):
                raise ValueError("Analysis cache must be outside the input tree")
            cache = None if args.inventory_only or args.preview_dir else create_analysis_cache(args, args.input)
            store = resources.enter_context(InventoryStore(inventory_path(args, args.input)).run())
            snapshot = SelectionSnapshot(store, args.input, owner="compresser")
            if args.inventory_policy == "trust":
                images, _ = snapshot.load()
                summary = summarize_images(args.input, images)
            else:
                prog = InventoryProgress(args.input, depth="headers", enabled=not args.no_ui and not args.json)
                try:
                    summary, images = scan_directory(
                        args.input, recursive=True, cache=cache, inventory=store, progress=prog, threads=args.threads
                    )
                finally:
                    prog.close()
                snapshot.publish(images)
            if args.inventory_only:
                report = inventory_report(images, args.input.expanduser().resolve())
                report.update(store.diagnostics())
                report["sampling_profile"] = snapshot.profile.data if snapshot.profile else None
                emit_inventory_report(report, as_json=args.json)
                return 0
        if not images:
            if args.json:
                print(json.dumps({"error": "No image files found in target path"}))
            else:
                print(f"No image files found in target: {args.input}", file=sys.stderr)
            return 1

        if args.preview_dir:
            from .preview import run_preview_cli

            return run_preview_cli(args, images, args.input)

        # Handle sample selection
        sampling_plan = gallery_sample(
            images,
            args.input,
            sample_size=args.sample,
            percent=args.sample_percent,
            seed=args.sample_seed,
            profile=snapshot.profile if args.sample == "auto" else None,
        )
        eval_images = sampling_plan.images
        snapshot.validate_selected(eval_images)
        sampling_plan.population_warning = snapshot.report.get("warning", "")
        store.save_sample(sampling_plan, args.input)
        from dataclasses import replace

        active_report = current_session()
        active_report.context = replace(
            active_report.context,
            sampling=sampling_plan.summary(),
            snapshot=dict(snapshot.report),
            cache=cache.diagnostics(),
        )
        engine = CompressionEngine(
            cache=cache, memory_budget_bytes=args.memory_budget_mib * 1024**2, memory_policy=args._memory_policy
        )

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
                qualities=args.preview_qualities,
                recipe_specs=args._compression_options.recipes,
                source_validator=snapshot.validate_selected,
                scratch_dir=args.scratch_dir,
            )
            comparison_report, report_artifacts = session.comparison(
                comp_rows, snapshot=snapshot.report, cache=cache.diagnostics()
            )
            if args.json:
                recommendations = recommend_comparison_strategies(comp_rows)
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
                        "retained_formats": list(r.retained_formats),
                        "pipeline": pipeline_report(),
                        "error_summary": r.error_summary,
                        "candidate_bytes": r.candidate_bytes,
                        "original_bytes": r.original_bytes,
                        "worker_diagnostics": r.worker_diagnostics,
                        "sampling": r.sampling,
                        "estimate": r.estimate,
                        "extrapolation": r.extrapolation,
                        "report_artifacts": report_artifacts,
                        "recommendations": recommendations,
                        "inventory_snapshot": snapshot.report,
                        "cache": {**cache.diagnostics(), "policy": args.cache_policy},
                    }
                    for r in comp_rows
                ]
                print(json.dumps(data, indent=2))
            else:
                session.render(comparison_report)
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
                scratch_dir=args.scratch_dir,
            )
        finally:
            if dash:
                dash.close()

        analysis_report, report_artifacts, extrapolation = session.analysis(
            batch_result, sampling_plan, strat, snapshot=snapshot.report, cache=cache.diagnostics()
        )
        if args.json:
            out = {
                "strategy": batch_result.strategy_name,
                "report_artifacts": report_artifacts,
                "extrapolation": extrapolation,
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
                "pipeline": pipeline_report(),
                "scope": "sample" if len(eval_images) < summary.total_images else "full",
                "inventory_images": summary.total_images,
                "inventory_bytes": summary.total_bytes,
                "estimate": sampling_plan.estimate(batch_result.results),
                "sampling": sampling_plan.summary(),
                "inventory_snapshot": snapshot.report,
                "cache": {**cache.diagnostics(), "policy": args.cache_policy},
            }
            print(json.dumps(out, indent=2))
        else:
            session.render(analysis_report)

        return 0 if batch_result.failed_count == 0 else 1

    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    except Exception as exc:
        if current_session():
            current_session().failure = str(exc)
        if args.verbose:
            import traceback

            traceback.print_exc()
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    finally:
        resources.close()
        if cache is not None:
            cache.close()


if __name__ == "__main__":
    sys.exit(main())
