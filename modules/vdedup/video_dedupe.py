#!/usr/bin/env python3
"""
vdedup.video_dedupe – CLI entrypoint

This CLI drives the staged pipeline and report application.

Typical usage:

  # Fast exact-dupe sweep (HDD-friendly)
  video-dedupe "D:\\Videos" -Q 1-2 -p *.mp4 -r -t 4 -C D:\\vd-cache.jsonl -R D:\\report.json -x -L

  # Thorough scan including pHash + subset detection
  video-dedupe "D:\\Videos" -Q 1-4 -u 8 -F 9 -T 14 -s -m 0.30 -t 16 -C D:\\vd-cache.jsonl -R D:\\report.json -x -L -g

  # Apply a previously generated report
  video-dedupe -A D:\\report.json -f -b D:\\Quarantine
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

# NOTE: absolute imports so the CLI works whether installed or run from source
from vdedup.pipeline import PipelineConfig, parse_pipeline, run_pipeline
from vdedup.progress import ProgressReporter
from vdedup.cache import HashCache
from vdedup.grouping import choose_winners
from vdedup.report import write_report, apply_report


def _normalize_patterns(patts: Optional[List[str]]) -> Optional[List[str]]:
    if not patts:
        return None
    out: List[str] = []
    for p in patts:
        s = (p or "").strip()
        if not s:
            continue
        if not any(ch in s for ch in "*?["):
            s = f"*.{s.lstrip('.')}"
        out.append(s)
    return out or None


def _banner_text(scan: bool, *, dry: bool, mode: str, threads: int, gpu: bool, backup: Optional[str]) -> str:
    rt = f"{'SCAN' if scan else 'APPLY'} {'DRY' if dry else 'LIVE'}"
    b = f"Run: {rt}  |  Mode: {mode}  |  Threads: {threads}  |  GPU: {'ON' if gpu else 'OFF'}"
    if backup:
        b += f"  |  Backup: {backup}"
    return b


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Find and remove duplicate/similar videos & files using a staged pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Directory (positional; optional for --apply-report)
    p.add_argument("directory", nargs="?", help="Root directory to scan")

    # Patterns & recursion
    p.add_argument("-p", "--pattern", action="append", help="Glob to include (repeatable), e.g. -p *.mp4 -p *.mkv")
    p.add_argument("-r", "--recursive", action="store_true", help="Recurse into subdirectories (unlimited depth)")

    # Pipeline stages
    p.add_argument(
        "-Q", "--pipeline",
        type=str, default="1-2",
        help="Stages to run: 1=size prefilter, 2=hashing, 3=metadata, 4=phash/subset. Examples: 1-2 or 1,3-4 or all"
    )

    # Mode label (informational only; printed in banner)
    p.add_argument("-M", "--mode", type=str, default="hash", help="Free-form label for the run (printed in the banner)")

    # Performance & GPU
    p.add_argument("-t", "--threads", type=int, default=8, help="Total worker threads (default: 8)")
    p.add_argument("-g", "--gpu", action="store_true", help="Hint FFmpeg to use NVDEC/CUDA for pHash/subset (if available)")

    # Metadata / pHash params
    p.add_argument("-u", "--duration-tolerance", dest="duration_tolerance", type=float, default=2.0,
                   help="Duration tolerance (seconds) for metadata grouping (default: 2.0)")
    p.add_argument("-F", "--phash-frames", dest="phash_frames", type=int, default=5,
                   help="Frames to sample for perceptual hash (default: 5)")
    p.add_argument("-T", "--phash-threshold", dest="phash_threshold", type=int, default=12,
                   help="Per-frame Hamming distance threshold for pHash (default: 12)")
    p.add_argument("-s", "--subset-detect", action="store_true",
                   help="Enable subset detection (find shorter cut-downs of longer videos)")
    p.add_argument("-m", "--subset-min-ratio", type=float, default=0.30,
                   help="Minimum short/long duration ratio for subset matches (default: 0.30)")

    # Live UI
    p.add_argument("-L", "--live", action="store_true", help="Show live TermDash UI")
    p.add_argument("-e", "--refresh-rate", dest="refresh_rate", type=float, default=0.2,
                   help="UI refresh rate in seconds (default: 0.2)")
    p.add_argument("-Z", "--stacked-ui", action="store_true", help="Force stacked UI (one metric per line)")
    p.add_argument("-W", "--wide-ui", action="store_true", help="Force wide UI (multi-column)")

    # Cache & report
    p.add_argument("-C", "--cache", type=str, help="Path to JSONL cache file (append-on-write, resumable)")
    p.add_argument("-R", "--report", type=str, help="Write JSON report to this path")

    # Apply report
    p.add_argument("-A", "--apply-report", type=str, help="Read a JSON report and delete/move all listed losers")
    p.add_argument("-b", "--backup", type=str, help="Move losers to this folder instead of deleting (apply-report mode)")
    p.add_argument("-f", "--force", action="store_true", help="Do not prompt for deletion (apply-report mode)")
    p.add_argument("-x", "--dry-run", action="store_true", help="No changes; just print / write report")

    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    # UI layout preference
    stacked_pref: Optional[bool] = True if args.stacked_ui else (False if args.wide_ui else None)

    # APPLY REPORT mode
    if args.apply_report:
        banner = _banner_text(False, dry=args.dry_run, mode="apply", threads=args.threads, gpu=False, backup=args.backup)
        reporter = ProgressReporter(enable_dash=bool(args.live), refresh_rate=args.refresh_rate, banner=banner, stacked_ui=stacked_pref)
        reporter.start()
        try:
            report_path = Path(args.apply_report).expanduser().resolve()
            if not report_path.exists():
                print(f"video-dedupe: error: report not found: {report_path}", file=sys.stderr)
                return 2

            base_root: Optional[Path] = None
            if args.directory:
                base_root = Path(args.directory).expanduser().resolve()

            backup = Path(args.backup).expanduser().resolve() if args.backup else None
            count, size = apply_report(report_path, dry_run=args.dry_run, force=args.force, backup=backup, base_root=base_root)
            reporter.set_results(dup_groups=0, losers_count=count, bytes_total=size)
            print(f"Report applied: removed/moved={count}; size={size/1_048_576:.2f} MiB")
            return 0
        finally:
            reporter.stop()

    # SCAN mode
    root_str = args.directory
    if not root_str:
        print("video-dedupe: error: the following arguments are required: directory", file=sys.stderr)
        return 2
    root = Path(root_str).expanduser().resolve()
    if not root.exists():
        print(f"video-dedupe: error: directory not found: {root}", file=sys.stderr)
        return 2

    patterns = _normalize_patterns(args.pattern)
    max_depth = None if args.recursive else 0

    cfg = PipelineConfig(
        threads=max(1, int(args.threads)),
        duration_tolerance=args.duration_tolerance,
        same_res=False,
        same_codec=False,
        same_container=False,
        phash_frames=args.phash_frames,
        phash_threshold=args.phash_threshold,
        subset_detect=bool(args.subset_detect),
        subset_min_ratio=args.subset_min_ratio,
        subset_frame_threshold=max(args.phash_threshold, 12),
        gpu=bool(args.gpu),
    )

    banner = _banner_text(True, dry=args.dry_run, mode=args.mode, threads=cfg.threads, gpu=cfg.gpu, backup=args.backup)
    reporter = ProgressReporter(enable_dash=bool(args.live), refresh_rate=args.refresh_rate, banner=banner, stacked_ui=stacked_pref)
    reporter.start()

    cache = HashCache(Path(args.cache)) if args.cache else None
    if cache:
        cache.open_append()

    try:
        stages = parse_pipeline(args.pipeline)
        groups = run_pipeline(
            root=root,
            patterns=patterns,
            max_depth=max_depth,
            selected_stages=stages,
            cfg=cfg,
            cache=cache,
            reporter=reporter,
        )

        keep_order = ["longer", "resolution", "video-bitrate", "newer", "smaller", "deeper"]
        winners = choose_winners(groups, keep_order)

        if args.report:
            write_report(Path(args.report), winners)
            print(f"Wrote report to: {args.report}")

        losers = [loser for (_keep, losers) in winners.values() for loser in losers]
        bytes_total = sum(int(getattr(l, "size", 0)) for l in losers)
        reporter.set_results(dup_groups=len(winners), losers_count=len(losers), bytes_total=bytes_total)
        return 0
    finally:
        if cache:
            cache.close()
        reporter.stop()


if __name__ == "__main__":
    sys.exit(main())
