#!/usr/bin/env python3
"""
MangaDL integration adapter for the compresser module.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from compresser import (
    AnalysisCache,
    CompressionEngine,
    CompressionStrategy,
    ImageMetadata,
    ScanSummary,
    scan_directory,
)
from compresser.cli import run_comparison
from compresser.sampling import validate_analysis_arguments, gallery_sample, print_sampling
from compresser.inventory import InventoryStore, inventory_path, inventory_report
from compresser.inventory_ui import InventoryProgress, emit_inventory_report
from compresser.snapshots import SelectionSnapshot
from compresser.cache import create_analysis_cache
from compresser.ui import (
    CompresserDashboard,
    print_comparison_matrix,
    print_single_summary,
    recommend_comparison_strategies,
    report_cancellation,
    print_cache_diagnostics,
)
from .library_index import read_source_manifest, scan_library, resolve_url_folders
from .input import canonicalize_url
from .library_guard import library_read_guard, library_write_guard

COVER_STEMS = frozenset({"cover", "folder", "front", "back", "poster"})


def _gallery_images(
    directory: Path,
    cache: AnalysisCache | None = None,
    *,
    recursive: bool = True,
    inventory=None,
    progress=None,
):
    summary, images = scan_directory(
        directory, recursive=recursive, cache=cache, inventory=inventory, progress=progress
    )
    # Covers aren't numbered page payloads; their reader identity must not change.
    return summary, [
        image
        for image in images
        if not image.path.is_symlink()
        and not image.path.name.startswith(".")
        and image.path.stem.casefold() not in COVER_STEMS
    ]


def _assert_library_idle(destination: Path) -> None:
    from .cli_core import _assert_no_active_mangadl_run

    for root in (destination, *destination.parents):
        if (root / ".mangadl").is_dir():
            if (root / ".mangadl" / "repair.lock").exists():
                raise ValueError(f"A guarded repair is active: {root}")
            _assert_no_active_mangadl_run(root)
            return


def discover_gallery_targets(
    destination: Path,
    url_filters: Sequence[str] = (),
    *,
    cache: AnalysisCache | None = None,
    inventory=None,
    collected=None,
    progress=None,
) -> list[Path]:
    """Find gallery directories under destination root."""
    if destination.expanduser().is_symlink():
        raise ValueError("Compression cannot target a linked gallery")
    dest = destination.expanduser().resolve()
    if not dest.is_dir():
        raise FileNotFoundError(f"Destination does not exist: {dest}")
    if dest.name.startswith(".") or dest.name == "_partial":
        raise ValueError("Compression cannot target hidden controls or partial downloads")

    # Check if destination itself directly contains images
    _, direct_images = _gallery_images(dest, cache, recursive=False, inventory=inventory, progress=progress)
    # A source-owned gallery may contain only chapter subdirectories. Do not
    # interpret an arbitrary library root's descendants as one gallery.
    is_gallery = bool(direct_images) or read_source_manifest(dest) is not None
    if url_filters:
        roots = [dest.parent] if is_gallery else [dest]
        indexed = scan_library(roots)
        selected = []
        for value in url_filters:
            if "://" in value:
                url = canonicalize_url(value)
                matches = resolve_url_folders(url, indexed)
                if len(matches) != 1 or matches[0].identity_status == "ambiguous":
                    raise ValueError(f"Compression URL is unresolved or ambiguous: {value}")
                target = matches[0].path
            else:
                targets = [dest] if is_gallery else [row.path for row in indexed]
                matches = [target for target in targets if target.name.casefold() == value.casefold()]
                if len(matches) != 1:
                    raise ValueError(f"Compression folder name is unresolved or ambiguous: {value}")
                target = matches[0]
            if is_gallery and target != dest:
                raise ValueError("Selected URL does not identify the explicitly targeted gallery")
            if not target.is_symlink() and target not in selected:
                selected.append(target)
        return selected
    if is_gallery:
        return [dest]

    # Gallery ownership stays first-level; pages may be nested beneath it.
    galleries: list[Path] = []
    entries = [
        entry
        for entry in sorted(dest.iterdir(), key=lambda p: str(p).casefold())
        if entry.is_dir() and not entry.name.startswith(".") and entry.name != "_partial" and not entry.is_symlink()
    ]
    if progress is not None and entries:
        progress.set_folder_total(len(entries))
    for idx, entry in enumerate(entries, 1):
        if progress is not None:
            progress.start_folder(entry, folders_done=idx, total_folders=len(entries))
        summary, imgs = _gallery_images(entry, cache, inventory=inventory, progress=progress)
        if imgs:
            galleries.append(entry)
            if collected is not None:
                collected[entry] = (summary, imgs)

    return galleries


def run_cli(args: argparse.Namespace) -> int:
    """Execute mangadl compress subcommand."""
    try:
        validate_analysis_arguments(args)
        destination = args.destination.expanduser()
        if not destination.is_dir() or destination.is_symlink():
            raise ValueError("Compression requires an existing, unlinked destination directory")
        if destination.resolve().name.startswith(".") or destination.resolve().name == "_partial":
            raise ValueError("Compression cannot target hidden controls or partial downloads")
        op_desc = (
            "mangadl compress -w"
            if args.write
            else (
                f"mangadl compress -l -D {getattr(args, 'inventory_depth', 'headers')}"
                if getattr(args, "inventory_only", False)
                else "mangadl compress"
            )
        )
        guard = (
            library_write_guard(args.destination, operation=op_desc)
            if args.write
            else library_read_guard(args.destination, operation=op_desc)
        )
        with guard:
            return _run_cli_owned(args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error in mangadl compress: {exc}", file=sys.stderr)
        return 2


def _run_cli_owned(args: argparse.Namespace) -> int:
    dest = args.destination.expanduser().resolve()
    url_filters = getattr(args, "url", None) or ()
    cache = None

    try:
        if getattr(args, "inventory_depth", "headers") == "files":
            from compresser.file_inventory import scan_file_inventory
            from compresser.scanner import IMAGE_EXTENSIONS

            single_gallery = read_source_manifest(dest) is not None or any(
                path.is_file()
                and not path.is_symlink()
                and not path.name.startswith(".")
                and path.suffix.lower() in IMAGE_EXTENSIONS
                and path.stem.casefold() not in COVER_STEMS
                for path in dest.iterdir()
            )
            prog = InventoryProgress(
                dest,
                depth="files",
                enabled=not getattr(args, "no_ui", False) and not getattr(args, "json", False),
            )
            try:
                report = scan_file_inventory(
                    dest,
                    inventory_path(args, dest),
                    exclude_stems=COVER_STEMS,
                    single_gallery=single_gallery,
                    progress=prog,
                )
            finally:
                prog.close()
            emit_inventory_report(report, as_json=getattr(args, "json", False))
            return 0
        if args.write:
            _assert_library_idle(dest)
        if getattr(args, "confirm_recovery", None) and not getattr(args, "recover", False):
            raise ValueError("--confirm-recovery requires --recover")
        if getattr(args, "recover", False):
            if args.url or args.compare or args.sample:
                raise ValueError("Recovery requires one exact directory, without URL/compare/sample selection")
            from compresser.recovery import run_recovery

            return run_recovery(dest, apply=args.write, confirmation=args.confirm_recovery, as_json=args.json)
        if not 1 <= args.quality <= 100 or not 0.80 <= args.perceptual_target <= 1.0:
            raise ValueError("Quality must be 1..100 and perceptual target 0.80..1.00")
        if args.threads < 1 or args.sample is not None and args.sample < 1:
            raise ValueError("Threads and sample must be positive")
        if args.write and args.compare:
            raise ValueError("Comparison is read-only; omit --write")
        if args.write and args.mode != "lossless" and not args.allow_lossy:
            raise ValueError("Lossy/perceptual writes require --allow-lossy")
        cache_path = getattr(args, "cache_file", None)
        if not 64 <= args.memory_budget_mib <= 4096:
            raise ValueError("Aggregate scheduling budget must be64..4096MiB")
        if cache_path and (cache_path.resolve() == dest or dest in cache_path.resolve().parents):
            raise ValueError("Analysis cache must be outside the destination tree")
        cache = (
            None
            if getattr(args, "inventory_only", False) or getattr(args, "preview_dir", None)
            else create_analysis_cache(args, dest)
        )
        store = InventoryStore(inventory_path(args, dest))
        snapshot = SelectionSnapshot(store, dest, owner="mangadl-pages", filters=url_filters)
        discovered = {}
        prog = InventoryProgress(
            dest,
            depth="headers",
            enabled=getattr(args, "inventory_policy", "refresh") != "trust"
            and not getattr(args, "no_ui", False)
            and not getattr(args, "json", False),
        )
        try:
            if getattr(args, "inventory_policy", "refresh") == "trust":
                saved_images, saved_keys = snapshot.load()
                if saved_images and saved_keys is None:
                    raise ValueError("Snapshot is missing manga ownership; use -U refresh")
                for image in saved_images:
                    gal = Path(saved_keys[image.path])
                    if gal not in discovered:
                        discovered[gal] = (None, [])
                    discovered[gal][1].append(image)
                gallery_paths = list(discovered)
            else:
                gallery_paths = discover_gallery_targets(
                    dest, url_filters, cache=cache, inventory=store, collected=discovered, progress=prog
                )
            if not gallery_paths:
                prog.close()
                if getattr(args, "inventory_only", False):
                    report = inventory_report([], dest)
                    report.update(store.diagnostics())
                    emit_inventory_report(report, as_json=getattr(args, "json", False))
                    return 0
                msg = f"No manga gallery directories with images found in: {dest}"
                if getattr(args, "json", False):
                    print(json.dumps({"error": msg}))
                else:
                    print(msg, file=sys.stderr)
                return 1

            # Collect all images across target galleries
            all_images: list[ImageMetadata] = []
            gallery_keys = {}
            format_counts: dict[str, int] = {}
            format_bytes: dict[str, int] = {}
            total_bytes = 0
            tall_count = 0
            gray_count = 0

            for idx, gal in enumerate(gallery_paths, 1):
                if gal in discovered:
                    s, imgs = discovered[gal]
                else:
                    prog.start_folder(gal, folders_done=idx, total_folders=len(gallery_paths))
                    s, imgs = _gallery_images(gal, cache, inventory=store, progress=prog)
                # Rebuild counts after cover exclusions; no excluded bytes count as savings.
                s = ScanSummary(
                    gal,
                    len(imgs),
                    sum(img.size_bytes for img in imgs),
                    {
                        fmt: sum(img.format.upper() == fmt for img in imgs)
                        for fmt in {img.format.upper() for img in imgs}
                    },
                    {
                        fmt: sum(img.size_bytes for img in imgs if img.format.upper() == fmt)
                        for fmt in {img.format.upper() for img in imgs}
                    },
                    sum(img.is_tall_for_webp for img in imgs),
                    sum(img.is_grayscale for img in imgs),
                )
                all_images.extend(imgs)
                gallery_keys.update({image.path: str(gal) for image in imgs})
                total_bytes += s.total_bytes
                tall_count += s.tall_images_count
                gray_count += s.grayscale_count
                for fmt, cnt in s.format_counts.items():
                    format_counts[fmt] = format_counts.get(fmt, 0) + cnt
                for fmt, b_cnt in s.format_bytes.items():
                    format_bytes[fmt] = format_bytes.get(fmt, 0) + b_cnt
        finally:
            prog.close()

        if getattr(args, "inventory_policy", "refresh") != "trust":
            snapshot.publish(all_images, gallery_keys)

        if getattr(args, "inventory_only", False):
            report = inventory_report(all_images, dest, gallery_keys=gallery_keys)
            report.update(store.diagnostics())
            emit_inventory_report(report, as_json=getattr(args, "json", False))
            return 0

        if not all_images:
            msg = f"No images found to process in: {dest}"
            if getattr(args, "json", False):
                print(json.dumps({"error": msg}))
            else:
                print(msg, file=sys.stderr)
            return 1

        summary = ScanSummary(
            target_path=dest,
            total_images=len(all_images),
            total_bytes=total_bytes,
            format_counts=format_counts,
            format_bytes=format_bytes,
            tall_images_count=tall_count,
            grayscale_count=gray_count,
        )

        if getattr(args, "preview_dir", None):
            from compresser.preview import run_preview_cli

            return run_preview_cli(args, all_images, dest)

        sampling_plan = gallery_sample(
            all_images,
            dest,
            sample_size=args.sample,
            percent=getattr(args, "sample_percent", None),
            seed=getattr(args, "sample_seed", 0),
            gallery_keys=gallery_keys,
        )
        eval_images = sampling_plan.images
        snapshot.validate_selected(eval_images)
        sampling_plan.population_warning = snapshot.report.get("warning", "")
        store.save_sample(sampling_plan, dest)
        if not args.json:
            snapshot.print_warning()
            print(f"Inventory: {store.path}")
            print(f"Trial cache: {cache.path or 'memory only'} | policy: {getattr(args, 'cache_policy', 'use')}")
            print_cache_diagnostics(cache.diagnostics(), startup=True)
            print_sampling(sampling_plan)
        engine = CompressionEngine(cache=cache, memory_budget_bytes=args.memory_budget_mib * 1024**2)

        # Comparison Mode
        if getattr(args, "compare", False):
            comp_rows = run_comparison(
                eval_images,
                engine,
                threads=getattr(args, "threads", 4),
                no_ui=getattr(args, "no_ui", False) or getattr(args, "json", False),
                mode=args.mode,
                quality=args.quality,
                perceptual_target=args.perceptual_target,
                encoder=getattr(args, "algorithm", "auto"),
                effort=getattr(args, "effort", 6),
                compare_both=getattr(args, "compare_both", False),
                sampling_plan=sampling_plan,
                qualities=getattr(args, "preview_qualities", None),
                source_validator=snapshot.validate_selected,
                scratch_dir=getattr(args, "scratch_dir", None),
            )
            if getattr(args, "json", False):
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
                        "error_summary": r.error_summary,
                        "candidate_bytes": r.candidate_bytes,
                        "original_bytes": r.original_bytes,
                        "worker_diagnostics": r.worker_diagnostics,
                        "sampling": r.sampling,
                        "estimate": r.estimate,
                        "recommendations": recommendations,
                        "inventory_snapshot": snapshot.report,
                        "cache": {
                            **cache.diagnostics(),
                            "policy": getattr(args, "cache_policy", "use"),
                        },
                    }
                    for r in comp_rows
                ]
                print(json.dumps(data, indent=2))
            else:
                print_comparison_matrix(comp_rows)
                print_cache_diagnostics(cache.diagnostics())
                snapshot.print_warning()
            return 0

        # Compression / Analysis Mode
        strat = CompressionStrategy(
            name=f"{args.format}-{args.mode}",
            format=args.format,
            mode=args.mode,
            quality=args.quality,
            perceptual_target=args.perceptual_target,
            allow_larger=getattr(args, "allow_larger", False),
            allow_lossy=getattr(args, "allow_lossy", False),
            encoder=getattr(args, "algorithm", "auto"),
            method=getattr(args, "effort", 6),
        )

        dash = None
        if not getattr(args, "no_ui", False) and not getattr(args, "json", False):
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
                threads=getattr(args, "threads", 4),
                progress_callback=cb,
                cancellation_callback=lambda active: report_cancellation(dash, active),
                activity_callback=dash.update_activity if dash else None,
                scratch_dir=getattr(args, "scratch_dir", None),
            )
        finally:
            if dash:
                dash.close()

        if getattr(args, "json", False):
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
                "inventory_snapshot": snapshot.report,
                "cache": {
                    **cache.diagnostics(),
                    "policy": getattr(args, "cache_policy", "use"),
                },
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
                advisor = estimate.get("pilot_advisor")
                if advisor and not advisor["precision_met"]:
                    print(
                        f"Pilot advisor (planning only): {advisor['recommended_total_samples']} total trials "
                        f"(+{advisor['recommended_additional_confirmation_samples']} samples, "
                        f"~{advisor['estimated_additional_runtime_seconds']:.1f}s) for "
                        f"+/-{advisor['target_margin_percent']:g}% target margin under its proposed quotas. "
                        "Ordinary -s does not apply those quotas; this is not a precision guarantee."
                    )
                print(estimate["uncertainty"])
            print_cache_diagnostics(cache.diagnostics())
            snapshot.print_warning()

        return 0 if batch_result.failed_count == 0 else 1

    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    except Exception as exc:
        if getattr(args, "verbose", 0):
            import traceback

            traceback.print_exc()
        print(f"Error in mangadl compress: {exc}", file=sys.stderr)
        return 2
    finally:
        if cache is not None:
            cache.close()
