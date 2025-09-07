#!/usr/bin/env python3
"""
Video & File Deduplicator (modular)

- Q-Pipeline: size → partial+BLAKE3 → full SHA-256 (collisions) → metadata → pHash (+subset)
- Resumable JSONL cache (sha256, partials, ffprobe meta, pHash)
- Unified threads, responsive dashboard, GPU-assisted pHash, report/apply modes
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

try:
    from rich.console import Console
    RICH_AVAILABLE = True
except Exception:
    RICH_AVAILABLE = False
console = Console() if RICH_AVAILABLE else None

from vdedup.cache import HashCache
from vdedup.pipeline import PipelineConfig, parse_pipeline, run_pipeline
from vdedup.grouping import choose_winners
from vdedup.progress import ProgressReporter
from vdedup.report import write_report, apply_report


def _print(msg: str):
    if console:
        console.print(msg)
    else:
        print(msg)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    epilog = r"""
Examples:

  # Fast exact duplicates first (Q1-2), dry-run:
  python .\video_dedupe.py "D:\Videos" -Q 1-2 -M hash -p *.mp4 -r -t 8 -C D:\vd-cache.jsonl -R D:\report.json -x -L

  # Maximize matches & prefer longer (mixed libraries):
  python .\video_dedupe.py "D:\Videos" -Q 1-4 -M all -u 8 -F 9 -T 14 -s -m 0.30 -t 16 -C D:\vd-cache.jsonl -R D:\report.json -x -L

  # Force stacked UI (narrow terminal):
  python .\video_dedupe.py "D:\Videos" -M all -Z -x -L

  # Apply a previously generated report:
  python .\video_dedupe.py -A D:\report.json -f -b D:\Quarantine
"""
    p = argparse.ArgumentParser(
        description="Find and report duplicate/similar videos & files (including subset cut-downs). Apply deletions with --apply-report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog
    )

    # Directory to scan (positional)
    p.add_argument("directory", help="Root directory to scan")

    # Mode (kept for compatibility with your workflows; affects grouping/keep policy hints)
    p.add_argument("-M", "--mode", choices=["hash", "meta", "phash", "all"], default="hash",
                   help="Detection mode focus (hash/meta/phash/all). Does not override -Q stages; acts as a hint.")

    # Patterns & recursion
    p.add_argument("-p", "--pattern", action="append", help="Glob include pattern(s) like *.mp4 (repeatable)")
    p.add_argument("-r", "--recursive", nargs="?", const=-1, type=int,
                   help="Recurse depth: omit for none; -r for unlimited; -r N for depth N")

    # Pipeline
    p.add_argument("-Q", "--pipeline", type=str, default="1-4",
                   help="Stages to run: 1=size, 2=partial+sha256, 3=metadata, 4=phash(+subset). Examples: '1-2', '2,4', '1,3-4'")

    # Metadata
    p.add_argument("-u", "--duration-tolerance", type=float, default=2.0, help="Duration tolerance seconds (default: 2.0)")
    p.add_argument("-S", "--same-res", action="store_true", help="Require same resolution for metadata grouping")
    p.add_argument("-Cw", "--same-codec", action="store_true", help="Require same video codec for metadata grouping")
    p.add_argument("-Cn", "--same-container", action="store_true", help="Require same container for metadata grouping")

    # pHash / subset
    p.add_argument("-F", "--phash-frames", type=int, default=5, help="Frames to sample for pHash (default: 5)")
    p.add_argument("-T", "--phash-threshold", type=int, default=12, help="Per-frame Hamming distance threshold (default: 12)")
    p.add_argument("-s", "--subset-detect", action="store_true", help="Enable subset detection (short vs long)")
    p.add_argument("-m", "--subset-min-ratio", type=float, default=0.30, help="Minimum short/long duration ratio (default: 0.30)")
    p.add_argument("-H", "--subset-frame-threshold", type=int, default=18, help="Per-frame threshold for subset alignment (default: 18)")
    p.add_argument("-g", "--gpu", action="store_true", help="Hint FFmpeg to use NVDEC/CUDA for pHash frames (if available)")

    # Hashing knobs
    p.add_argument("-t", "--threads", type=int, default=8, help="Total worker threads to use (I/O-bound steps)")
    p.add_argument("-B", "--block-size", type=int, default=1 << 20, help="Hashing block size in bytes (default: 1 MiB)")

    # Keep policy
    p.add_argument("-k", "--keep", type=str,
                   default="longer,resolution,video-bitrate,newer,smaller,deeper",
                   help="Keep-order preference (comma list). Default favors longer videos.")

    # Actions & outputs
    p.add_argument("-x", "--dry-run", action="store_true", help="Do not delete files; still writes report/cache")
    p.add_argument("-f", "--force", action="store_true", help="No prompt when applying a report")
    p.add_argument("-b", "--backup", type=str, help="Move losers to this folder when applying a report")

    p.add_argument("-R", "--report", type=str, help="Write JSON report to this path")
    p.add_argument("-A", "--apply-report", type=str, help="Read a JSON report and delete/move all listed losers")

    # Live dashboard (+ layout controls)
    p.add_argument("-L", "--live", action="store_true", help="Show live, in-place progress with TermDash")
    p.add_argument("-e", "--refresh-rate", dest="refresh_rate", type=float, default=0.2, help="Dashboard refresh rate seconds (default: 0.2)")
    p.add_argument("-Z", "--stacked-ui", action="store_true", help="Force stacked UI (one metric per line)")
    p.add_argument("-W", "--wide-ui", action="store_true", help="Force wide UI (multi-column)")

    # Cache
    p.add_argument("-C", "--cache", type=str, help="Path to JSONL cache file (enables cache read/write)")

    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    # Apply-report mode short-circuit
    if args.apply_report:
        run_type = f"Run: APPLY {'DRY' if args.dry_run else 'LIVE'} | Backup: {'YES' if args.backup else 'NO'}"
        reporter = ProgressReporter(enable_dash=bool(args.live), refresh_rate=args.refresh_rate, banner=run_type,
                                    stacked_ui=(True if args.stacked_ui else (False if args.wide_ui else None)))
        reporter.start()
        try:
            report_path = Path(args.apply_report).expanduser().resolve()
            if not report_path.exists():
                _print(f"[red]Report not found:[/] {report_path}" if console else f"Report not found: {report_path}")
                return 2
            backup = Path(args.backup).expanduser().resolve() if args.backup else None
            count, total = apply_report(report_path, dry_run=args.dry_run, force=args.force, backup=backup, base_root=None)
            _print(f"Report applied: removed/moved={count}; size={total/1_048_576:.2f} MiB")
            return 0
        finally:
            reporter.stop()

    # Scan/pipeline mode
    root = Path(args.directory).expanduser().resolve()
    if not root.exists():
        _print(f"[red]Directory not found:[/] {root}" if console else f"Directory not found: {root}")
        return 2

    # Determine depth
    if args.recursive is None:
        max_depth: Optional[int] = 0
    elif args.recursive == -1:
        max_depth = None
    else:
        max_depth = max(0, int(args.recursive))

    selected = parse_pipeline(args.pipeline)

    # Banner
    run_type = f"Run: SCAN {'DRY' if args.dry_run else 'LIVE'} | Mode: {args.mode} | Threads: {args.threads} | GPU: {'YES' if args.gpu else 'NO'} | Backup: {'YES' if args.backup else 'NO'}"
    reporter = ProgressReporter(enable_dash=bool(args.live), refresh_rate=args.refresh_rate, banner=run_type,
                                stacked_ui=(True if args.stacked_ui else (False if args.wide_ui else None)))
    reporter.start()

    cache = HashCache(Path(args.cache)) if args.cache else None
    if cache:
        cache.open_append()

    try:
        cfg = PipelineConfig(
            threads=args.threads,
            block_size=args.block_size,
            duration_tolerance=args.duration_tolerance,
            same_res=args.same_res,
            same_codec=args.same_codec,
            same_container=args.same_container,
            phash_frames=args.phash_frames,
            phash_threshold=args.phash_threshold,
            subset_detect=args.subset_detect,
            subset_min_ratio=args.subset_min_ratio,
            subset_frame_threshold=args.subset_frame_threshold,
            gpu=args.gpu,
        )

        groups = run_pipeline(
            root=root,
            patterns=args.pattern,
            max_depth=max_depth,
            selected_stages=selected,
            cfg=cfg,
            cache=cache,
        )

        if not groups:
            _print("No duplicate groups found.")
            return 0

        keep_order = [t.strip() for t in args.keep.split(",") if t.strip()]
        winners = choose_winners(groups, keep_order)

        if args.report:
            write_report(Path(args.report), winners)
            _print(f"Wrote report to: {args.report}")

        losers = [l for (_, ls) in winners.values() for l in ls]
        reporter.losers_total = len(losers)
        reporter.bytes_to_remove = sum(getattr(l, "size", 0) or 0 for l in losers)
        reporter.flush()

        _print(f"Candidates: {len(losers)} across {len(winners)} groups. Size={reporter.bytes_to_remove/1_048_576:.2f} MiB. Use --apply-report to delete or backup.")
        return 0

    except KeyboardInterrupt:
        _print("Aborted by user (Ctrl+C).")
        return 130
    finally:
        if cache:
            cache.close()
        reporter.stop()


if __name__ == "__main__":
    sys.exit(main())
