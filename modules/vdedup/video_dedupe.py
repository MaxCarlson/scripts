#!/usr/bin/env python3
"""
vdedup.video_dedupe – CLI entrypoint

This CLI drives the staged pipeline and report application.

Examples:

  # Fast exact-dupe sweep (HDD-friendly)
  video-dedupe "D:\\Videos" -Q 1-2 -p *.mp4 -r -t 4 -C D:\\vd-cache.jsonl -R D:\\report.json -x -L

  # Thorough scan including pHash + subset detection
  video-dedupe "D:\\Videos" -Q 1-4 -u 8 -F 9 -T 14 -s -m 0.30 -t 16 -C D:\\vd-cache.jsonl -R D:\\report.json -x -L -g

  # Apply a previously generated report
  video-dedupe -A D:\\report.json -f -b D:\\Quarantine

  # Print one or more reports (with verbosity)
  video-dedupe -P D:\\report.json -V 2

  # Analyze report(s): print winner↔loser diffs (duration, resolution, bitrates, size)
  video-dedupe -Y D:\\report.json --diff-verbosity 1
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# NOTE: absolute imports so the CLI works whether installed or run from source
from vdedup.pipeline import PipelineConfig, parse_pipeline, run_pipeline
from vdedup.progress import ProgressReporter
from vdedup.cache import HashCache
from vdedup.grouping import choose_winners
from vdedup.report import (
    write_report,
    apply_report,
    pretty_print_reports,
    collect_exclusions,
    load_report,
    collapse_report_file,
)

# -------- helpers --------

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


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024**2:
        return f"{n/1024:.2f} KiB"
    if n < 1024**3:
        return f"{n/1024**2:.2f} MiB"
    return f"{n/1024**3:.2f} GiB"


# --- analysis helpers (kept here so tests can monkeypatch) ---

def _fmt_dur(sec: Optional[float]) -> str:
    try:
        s = int(sec or 0)
        return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"
    except Exception:
        return "--:--:--"


def _probe_stats(path: Path) -> Dict[str, Any]:
    """
    Lightweight probe used by analysis mode.
    Returns dict: duration, width, height, overall_bitrate, video_bitrate, size.
    """
    size = 0
    try:
        st = path.stat()
        size = int(st.st_size)
    except Exception:
        pass

    duration = None
    width = height = None
    overall_bitrate = None
    video_bitrate = None
    try:
        from vdedup.probe import run_ffprobe_json  # lazy
        fmt = run_ffprobe_json(path)
        if fmt:
            try:
                duration = float(fmt.get("format", {}).get("duration", 0.0))
            except Exception:
                duration = None
            try:
                br = fmt.get("format", {}).get("bit_rate", None)
                overall_bitrate = int(br) if br is not None else None
            except Exception:
                overall_bitrate = None
            for s in fmt.get("streams", []):
                if s.get("codec_type") == "video":
                    try:
                        video_bitrate = int(s.get("bit_rate")) if s.get("bit_rate") is not None else None
                    except Exception:
                        video_bitrate = None
                    try:
                        width = int(s.get("width") or 0) or None
                        height = int(s.get("height") or 0) or None
                    except Exception:
                        width = height = None
                    break
    except Exception:
        pass

    return {
        "size": size,
        "duration": duration,
        "width": width,
        "height": height,
        "overall_bitrate": overall_bitrate,
        "video_bitrate": video_bitrate,
    }


def _render_pair_diff(keep: Path, lose: Path, a: Dict[str, Any], b: Dict[str, Any]) -> List[str]:
    """
    Render left-justified stats with deltas.
    """
    lines: List[str] = []
    lines.append(f"KEEP: {keep}")
    lines.append(f"LOSE: {lose}")

    def col(label: str, av: Any, bv: Any, fmt=lambda x: str(x)):
        la = fmt(av) if av is not None else "—"
        lb = fmt(bv) if bv is not None else "—"
        delta = None
        if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
            dv = av - bv
            if abs(dv) > 0:
                delta = f"{'+' if dv>=0 else ''}{dv}"
        lines.append(f"  {label:<14}: {la:<12} vs {lb:<12}" + (f"  Δ {delta}" if delta is not None else ""))

    # duration
    col("duration", a.get("duration"), b.get("duration"), _fmt_dur)
    # resolution
    resa = f"{a.get('width','?')}x{a.get('height','?')}" if a.get("width") and a.get("height") else None
    resb = f"{b.get('width','?')}x{b.get('height','?')}" if b.get("width") and b.get("height") else None
    lines.append(f"  {'resolution':<14}: {resa or '—':<12} vs {resb or '—':<12}")
    # video bitrate
    col("v_bitrate", a.get("video_bitrate"), b.get("video_bitrate"))
    # overall bitrate
    col("overall_bps", a.get("overall_bitrate"), b.get("overall_bitrate"))
    # size
    col("size", a.get("size"), b.get("size"), _fmt_bytes)

    return lines


# ---------- robust single-line progress bar ----------

class _TextProgress:
    """
    A very small progress bar that overwrites a single line reliably.

    Uses ANSI 'erase line' + carriage return to avoid consoles that ignore '\r'.
    Falls back to printing normally if not a TTY.
    """
    def __init__(self, total: int, label: str = "Processing"):
        self.total = max(0, int(total))
        self.label = label
        self.n = 0
        self.start = time.time()
        self._last_render = 0.0
        self._tty = sys.stdout.isatty()

    def _fmt_hms(self, sec: Optional[float]) -> str:
        if sec is None or sec < 0:
            return "--:--"
        s = int(sec)
        return f"{s//60:02d}:{s%60:02d}"

    def _render(self, force: bool = False):
        now = time.time()
        if not force and (now - self._last_render) < 0.05:
            return
        self._last_render = now

        cols = shutil.get_terminal_size(fallback=(80, 20)).columns
        barw = max(10, min(40, cols - 40))
        pct = 0.0 if self.total == 0 else min(1.0, self.n / self.total)
        filled = int(barw * pct)
        elapsed = now - self.start
        rate = self.n / elapsed if elapsed > 0 else 0.0
        eta = (self.total - self.n) / rate if rate > 0 else None

        if self._tty:
            # ANSI: erase line + carriage to col 0
            sys.stdout.write("\x1b[2K\r")
            sys.stdout.write(f"{self.label} [{'#'*filled}{'-'*(barw - filled)}] {self.n}/{self.total}  {pct*100:5.1f}%  ETA {self._fmt_hms(eta)}")
            sys.stdout.flush()
        else:
            # Non-tty: print once every so often
            if force or (self.n == self.total) or filled % 4 == 0:
                print(f"{self.label} {self.n}/{self.total} ({pct*100:5.1f}%)")

    def update(self, n: int = 1):
        self.n += int(n)
        self._render()

    def close(self):
        self._render(force=True)
        if self._tty:
            sys.stdout.write("\x1b[2K\r")  # clear line
            sys.stdout.flush()


# -------- report analysis printer with progress --------

def render_analysis_for_reports(paths: List[Path], verbosity: int = 1, *, show_progress: bool = True) -> str:
    """
    Produce a readable diff for each (keep, loser) pair in one or more reports.
    verbosity currently:
      0 = totals only (number of pairs)
      1 = per-group winner/loser pairs with stat lines

    Always ends with a global summary (groups, losers, space).
    While running, a textual progress bar is shown if show_progress=True and stdout is a TTY.
    """
    out: List[str] = []
    total_pairs = 0

    # overall counters
    overall_groups = 0
    overall_losers = 0
    overall_space_bytes = 0

    # Pre-count total pairs for the progress bar
    planned_pairs = 0
    for rp in paths:
        try:
            d = load_report(rp)
            groups = d.get("groups") or {}
            for g in groups.values():
                planned_pairs += len(g.get("losers") or [])
        except Exception:
            continue

    prog: Optional[_TextProgress] = None
    if show_progress and sys.stdout.isatty():
        prog = _TextProgress(planned_pairs, label="Analyzing report(s)")

    for rp in paths:
        data = load_report(rp)
        groups = data.get("groups") or {}

        # pull summary if present to count groups/losers quickly
        if isinstance(data.get("summary"), dict):
            try:
                overall_groups += int(data["summary"].get("groups", 0) or 0)
                overall_losers += int(data["summary"].get("losers", 0) or 0)
                overall_space_bytes += int(data["summary"].get("size_bytes", 0) or 0)
            except Exception:
                pass
        else:
            overall_groups += len(groups)
            for g in groups.values():
                overall_losers += len(g.get("losers") or [])

        if not groups:
            continue

        out.append(f"Analysis: {rp}")
        for gid, g in groups.items():
            keep = Path(g.get("keep", ""))
            losers = [Path(x) for x in (g.get("losers") or [])]
            if verbosity >= 1:
                out.append(f"  [{g.get('method', 'unknown')}] {gid}")
            for l in losers:
                total_pairs += 1
                a = _probe_stats(keep)
                b = _probe_stats(l)
                # If report summary didn't contain size_bytes, accumulate via probing
                if not isinstance(data.get("summary"), dict) or "size_bytes" not in data["summary"]:
                    try:
                        overall_space_bytes += int(b.get("size") or 0)
                    except Exception:
                        pass
                if verbosity >= 1:
                    out.extend(f"    {line}" for line in _render_pair_diff(keep, l, a, b))
                if prog:
                    prog.update(1)
        out.append("")

    if prog:
        prog.close()

    # Bottom-of-report overall stats
    out.append("Overall totals:")
    out.append(f"  Duplicates (groups): {overall_groups}")
    out.append(f"  Videos to delete   : {overall_losers}")
    out.append(f"  Space to save      : {_fmt_bytes(overall_space_bytes)}")
    out.append(f"  Total pairs analyzed: {total_pairs}")

    return "\n".join(out)


# -------- CLI parsing --------

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Find and remove duplicate/similar videos & files using a staged pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Directories (positional; 0+ so that --apply-report works without any)
    p.add_argument("directories", nargs="*", help="One or more root directories to scan")

    # Patterns & recursion
    p.add_argument("-p", "--pattern", action="append", help="Glob to include (repeatable), e.g. -p *.mp4 -p *.mkv")
    p.add_argument("-r", "--recursive", action="store_true", help="Recurse into subdirectories (unlimited depth)")

    # Pipeline stages
    p.add_argument(
        "-Q", "--pipeline",
        type=str, default="1-2",
        help="Stages to run: 1=size prefilter, 2=hashing, 3=metadata, 4=phash/subset. You may also pass 5 (no-op) for convenience. Examples: 1-2 or 1,3-4 or all"
    )

    # Mode label (informational only; printed in the banner)
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

    # Report utilities
    p.add_argument("-P", "--print-report", action="append", help="Path to a JSON report to pretty-print (repeatable)")
    p.add_argument("-V", "--verbosity", type=int, default=1, choices=[0, 1, 2], help="Report/apply verbosity (0–2). Default: 1")
    p.add_argument("-X", "--exclude-by-report", action="append", help="Path to a JSON report; losers listed will be skipped during scan (repeatable)")

    # Report analysis
    p.add_argument("-Y", "--analyze-report", action="append", help="Path to a JSON report to analyze (winner↔loser diffs). Repeatable.")
    p.add_argument("-D", "--diff-verbosity", type=int, default=1, choices=[0, 1], help="Analysis verbosity. 0=totals only, 1=pairs with stats.")
    p.add_argument("-N", "--no-progress", action="store_true", help="Disable textual progress bar during report analysis.")

    # Apply report
    p.add_argument("-A", "--apply-report", type=str, help="Read a JSON report and delete/move all listed losers (or vault + hardlink if --vault is provided)")
    p.add_argument("-b", "--backup", type=str, help="Move losers to this folder instead of deleting (apply-report mode)")
    p.add_argument("-U", "--vault", type=str, help="Vault root for canonical content. With -A, move winner into the vault and hardlink original paths to it.")
    p.add_argument("-f", "--force", action="store_true", help="Do not prompt for deletion (apply-report mode)")
    p.add_argument("-x", "--dry-run", action="store_true", help="No changes; just print / write report")
    p.add_argument("-E", "--full-file-names", action="store_true", help="Show full original paths in apply output (disable compact vset aliases)")

    # Collapse report
    p.add_argument("-k", "--collapse-report", type=str, help="Collapse an existing report by merging overlapping groups.")
    p.add_argument("-o", "--out", type=str, help="Output path for --collapse-report")

    return p.parse_args(argv)


def _maybe_print_or_analyze(args: argparse.Namespace) -> Optional[int]:
    """
    If only -P/--print-report or -Y/--analyze-report were supplied (no directories / apply),
    do that and exit.
    """
    # Pretty print
    if args.print_report and not args.directories and not args.apply_report and not args.analyze_report:
        paths = [Path(p).expanduser().resolve() for p in args.print_report]
        text = pretty_print_reports(paths, verbosity=int(args.verbosity))
        print(text)
        return 0
    # Analyze
    if args.analyze_report and not args.directories and not args.apply_report:
        paths = [Path(p).expanduser().resolve() for p in args.analyze_report]
        text = render_analysis_for_reports(paths, verbosity=int(args.diff_verbosity), show_progress=not args.no_progress)
        print(text)
        return 0
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    # If they only want to print/analyze reports, do that and exit
    maybe = _maybe_print_or_analyze(args)
    if maybe is not None:
        return maybe

    # UI layout preference
    stacked_pref: Optional[bool] = True if args.stacked_ui else (False if args.wide_ui else None)

    # COLLAPSE REPORT mode
    if args.collapse_report:
        reporter = ProgressReporter(enable_dash=bool(args.live), refresh_rate=args.refresh_rate,
                                    banner="Run: COLLAPSE REPORT", stacked_ui=stacked_pref)
        reporter.start()
        try:
            in_path = Path(args.collapse_report).expanduser().resolve()
            if not in_path.exists():
                print(f"video-dedupe: error: report not found: {in_path}", file=sys.stderr)
                return 2
            out_path = Path(args.out).expanduser().resolve() if args.out else None
            out = collapse_report_file(in_path, out_path, reporter=reporter)
            print(f"Collapsed report written to: {out}")
            return 0
        finally:
            reporter.stop()

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

            # optional base (used only for --backup relative layout)
            base_root: Optional[Path] = None
            if args.directories:
                # when multiple directories are provided, compute a common base for backup layout
                try:
                    base_root = Path(os.path.commonpath([str(Path(d).expanduser().resolve()) for d in args.directories]))
                except Exception:
                    base_root = None

            backup = Path(args.backup).expanduser().resolve() if args.backup else None
            vault = Path(args.vault).expanduser().resolve() if args.vault else None
            count, size = apply_report(
                report_path,
                dry_run=args.dry_run,
                force=args.force,
                backup=backup,
                base_root=base_root,
                vault=vault,
                reporter=reporter,
                verbosity=int(args.verbosity),
                full_file_names=bool(args.full_file_names),
            )
            reporter.set_results(dup_groups=0, losers_count=count, bytes_total=size)
            if args.vault:
                print(f"Vaulted apply complete: linked {count} paths; space reclaimable: {size/1_048_576:.2f} MiB")
            else:
                print(f"Report applied: removed/moved={count}; size={size/1_048_576:.2f} MiB")
            return 0
        finally:
            reporter.stop()

    # SCAN mode
    if not args.directories:
        print("video-dedupe: error: the following arguments are required: one or more directories (or use -P/--print-report / -Y/--analyze-report)", file=sys.stderr)
        return 2

    roots = [Path(d).expanduser().resolve() for d in args.directories]
    for r in roots:
        if not r.exists():
            print(f"video-dedupe: error: directory not found: {r}", file=sys.stderr)
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

    # Build exclusion set from reports, if any
    skip_paths = set()
    if args.exclude_by_report:
        ex_paths = [Path(p).expanduser().resolve() for p in args.exclude_by_report]
        skip_paths = collect_exclusions(ex_paths)
        if skip_paths:
            print(f"Excluding {len(skip_paths)} files listed as losers in supplied report(s).")

    try:
        stages = parse_pipeline(args.pipeline)

        # Try to pass multiple roots if your pipeline supports it; else fall back to a single root run.
        groups: Dict[str, Tuple[Any, List[Any]]]
        try:
            groups = run_pipeline(
                roots=roots,                      # <— new: multiple roots, dedupes across them
                patterns=patterns,
                max_depth=max_depth,
                selected_stages=stages,
                cfg=cfg,
                cache=cache,
                reporter=reporter,
                skip_paths=skip_paths,
            )
        except TypeError:
            # Compatibility fallback: run the largest root (common parent) if it contains all roots,
            # otherwise run the first root and warn that cross-root dedupe may be incomplete.
            common: Optional[Path] = None
            try:
                common = Path(os.path.commonpath([str(r) for r in roots]))
            except Exception:
                common = None
            root = common if common and common.exists() else roots[0]
            if len(roots) > 1 and (common is None or common not in roots):
                print("Warning: current pipeline doesn’t accept multiple roots; running on the first directory only. Cross-root duplicates may be missed.", file=sys.stderr)
            groups = run_pipeline(
                root=root,
                patterns=patterns,
                max_depth=max_depth,
                selected_stages=stages,
                cfg=cfg,
                cache=cache,
                reporter=reporter,
                skip_paths=skip_paths,
            )

        keep_order = ["longer", "resolution", "video-bitrate", "newer", "smaller", "deeper"]
        winners = choose_winners(groups, keep_order)

        if args.report:
            write_report(Path(args.report), winners)
            print(f"Wrote report to: {args.report}")

        losers = [loser for (_keep, losers) in winners.values() for loser in losers]
        bytes_total = sum(int(getattr(l, "size", 0)) for l in losers)
        reporter.set_results(dup_groups=len(winners), losers_count=len(losers), bytes_total=bytes_total)

        # If they also passed -P or -Y with directories, run those too (after scan)
        if args.print_report:
            paths = [Path(p).expanduser().resolve() for p in args.print_report]
            print(pretty_print_reports(paths, verbosity=int(args.verbosity)))
        if args.analyze_report:
            paths = [Path(p).expanduser().resolve() for p in args.analyze_report]
            print(render_analysis_for_reports(paths, verbosity=int(args.diff_verbosity), show_progress=not args.no_progress))

        return 0
    finally:
        if cache:
            cache.close()
        reporter.stop()


if __name__ == "__main__":
    sys.exit(main())
