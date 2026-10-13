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
    select_sample,
)
from compresser.cli import run_comparison
from compresser.estimates import estimate_savings
from compresser.ui import CompresserDashboard, print_comparison_matrix, print_single_summary
from .library_index import scan_library, resolve_url_folders
from .input import canonicalize_url


def _gallery_images(directory: Path, cache: AnalysisCache | None = None):
    summary, images = scan_directory(directory, recursive=False, cache=cache)
    # Covers aren't numbered page payloads; their reader identity must not change.
    return summary, [
        image for image in images if image.path.stem.casefold() not in {"cover", "folder", "front", "back", "poster"}
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
    destination: Path, url_filters: Sequence[str] = (), *, cache: AnalysisCache | None = None
) -> list[Path]:
    """Find gallery directories under destination root."""
    dest = destination.expanduser().resolve()
    if not dest.is_dir():
        raise FileNotFoundError(f"Destination does not exist: {dest}")
    if dest.name.startswith(".") or dest.name == "_partial":
        raise ValueError("Compression cannot target hidden controls or partial downloads")

    # Check if destination itself directly contains images
    direct_summary, direct_images = _gallery_images(dest, cache)
    if url_filters:
        roots = [dest.parent] if direct_images else [dest]
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
                targets = [dest] if direct_images else [row.path for row in indexed]
                matches = [target for target in targets if target.name.casefold() == value.casefold()]
                if len(matches) != 1:
                    raise ValueError(f"Compression folder name is unresolved or ambiguous: {value}")
                target = matches[0]
            if direct_images and target != dest:
                raise ValueError("Selected URL does not identify the explicitly targeted gallery")
            if not target.is_symlink() and target not in selected:
                selected.append(target)
        return selected
    if direct_images:
        return [dest]

    # Otherwise scan first-level subdirectories (galleries)
    galleries: list[Path] = []
    for entry in sorted(dest.iterdir(), key=lambda p: str(p).casefold()):
        if entry.is_dir() and not entry.name.startswith(".") and entry.name != "_partial" and not entry.is_symlink():
            summary, imgs = _gallery_images(entry, cache)
            if imgs:
                galleries.append(entry)

    return galleries


def run_cli(args: argparse.Namespace) -> int:
    """Execute mangadl compress subcommand."""
    dest = args.destination.expanduser().resolve()
    url_filters = getattr(args, "url", None) or ()

    try:
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
        if cache_path and (cache_path.resolve() == dest or dest in cache_path.resolve().parents):
            raise ValueError("Analysis cache must be outside the destination tree")
        cache = AnalysisCache(path=cache_path)
        gallery_paths = discover_gallery_targets(dest, url_filters, cache=cache)
        if not gallery_paths:
            msg = f"No manga gallery directories with images found in: {dest}"
            if getattr(args, "json", False):
                print(json.dumps({"error": msg}))
            else:
                print(msg, file=sys.stderr)
            return 1

        # Collect all images across target galleries
        all_images: list[ImageMetadata] = []
        format_counts: dict[str, int] = {}
        format_bytes: dict[str, int] = {}
        total_bytes = 0
        tall_count = 0
        gray_count = 0

        for gal in gallery_paths:
            s, imgs = _gallery_images(gal, cache)
            # Rebuild counts after cover exclusions; no excluded bytes count as savings.
            s = ScanSummary(
                gal,
                len(imgs),
                sum(img.size_bytes for img in imgs),
                {fmt: sum(img.format.upper() == fmt for img in imgs) for fmt in {img.format.upper() for img in imgs}},
                {
                    fmt: sum(img.size_bytes for img in imgs if img.format.upper() == fmt)
                    for fmt in {img.format.upper() for img in imgs}
                },
                sum(img.is_tall_for_webp for img in imgs),
                sum(img.is_grayscale for img in imgs),
            )
            all_images.extend(imgs)
            total_bytes += s.total_bytes
            tall_count += s.tall_images_count
            gray_count += s.grayscale_count
            for fmt, cnt in s.format_counts.items():
                format_counts[fmt] = format_counts.get(fmt, 0) + cnt
            for fmt, b_cnt in s.format_bytes.items():
                format_bytes[fmt] = format_bytes.get(fmt, 0) + b_cnt

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

        eval_images = select_sample(all_images, args.sample) if getattr(args, "sample", None) else all_images
        engine = CompressionEngine(cache=cache)

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
            )
            if getattr(args, "json", False):
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
                    }
                    for r in comp_rows
                ]
                print(json.dumps(data, indent=2))
            else:
                print_comparison_matrix(comp_rows)
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
                "scope": "sample" if len(eval_images) < summary.total_images else "full",
                "inventory_images": summary.total_images,
                "inventory_bytes": summary.total_bytes,
                "estimate": estimate_savings(all_images, batch_result.results),
            }
            print(json.dumps(out, indent=2))
        else:
            print_single_summary(batch_result, scan=summary)
            estimate = estimate_savings(all_images, batch_result.results)
            if estimate["scope"] != "full":
                print(
                    f"Projected savings for covered strata: {estimate['projected_covered_saved_bytes']:,} bytes; "
                    f"{estimate['unestimated_images']} images remain unestimated."
                )
                print(estimate["uncertainty"])

        return 0 if batch_result.failed_count == 0 else 1

    except Exception as exc:
        if getattr(args, "verbose", 0):
            import traceback

            traceback.print_exc()
        print(f"Error in mangadl compress: {exc}", file=sys.stderr)
        return 2
