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

  # Analyze report(s): print winner<->loser diffs (duration, resolution, bitrates, size)
  video-dedupe -Y D:\\report.json --diff-verbosity 1
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

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


def _setup_logging(log_file: Optional[Path] = None, log_level: str = "INFO", console_level: str = "WARNING") -> logging.Logger:
    """
    Configure comprehensive logging for video deduplication operations.

    Args:
        log_file: Path to log file (if None, logs to output directory)
        log_level: File logging level (DEBUG, INFO, WARNING, ERROR)
        console_level: Console logging level (DEBUG, INFO, WARNING, ERROR)

    Returns:
        Configured logger instance
    """
    # Create logger
    logger = logging.getLogger('vdedup')
    logger.setLevel(logging.DEBUG)  # Capture everything, filter at handler level

    # Clear any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # File handler (detailed logging)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
        file_handler.setLevel(getattr(logging, log_level.upper()))

        # Detailed format for file
        file_format = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(funcName)-20s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

    # Console handler (less verbose)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(getattr(logging, console_level.upper()))

    # Simple format for console
    console_format = logging.Formatter('%(levelname)s: %(message)s')
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    return logger


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


# ========================
# QoL: auto-named outputs
# ========================

def _q_tag(pipeline: str) -> str:
    """
    Build a compact 'q...' tag from a pipeline spec.
    Examples: '1' -> 'q1', '1-2' -> 'q1-2', 'all' -> 'qall'
    """
    ps = (pipeline or "").strip()
    if not ps:
        return "q"
    if any(ch.isdigit() for ch in ps):
        keep = "".join(ch for ch in ps if (ch.isdigit() or ch == "-"))
        return f"q{keep or ''}" if keep else "q"
    return f"q{ps.replace(' ', '')}"


def _auto_outputs(prefix: Optional[str], name: Optional[str], pipeline: str) -> Tuple[Optional[Path], Optional[Path]]:
    """
    Returns (cache_path, report_path) or (None, None) if insufficient info.
    """
    if not prefix or not name:
        return (None, None)
    tag = _q_tag(pipeline)
    base = Path(prefix).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    cache = base / f"{name}-{tag}-cache.jsonl"
    report = base / f"{name}-{tag}-report.json"
    return (cache, report)


# =============================================
# Per-directory recursion: DIR::dN / DIR::r / globs
# =============================================

def _parse_dir_spec(spec: str, default_depth: Optional[int]) -> Tuple[str, Optional[int]]:
    """
    Take a raw directory spec and return (pattern, depth).
    pattern may contain glob characters (*, ?, []).
    depth: None = unlimited, 0,1,2,..., or -1 treated as unlimited.
    Syntax:
      "<path>"             -> uses default_depth
      "<path>::dN"         -> depth N
      "<path>::r"          -> unlimited
      "<glob>*::d0"        -> depth 0 applied to each match
    """
    s = spec
    depth = default_depth
    # split on the *last* '::' so Windows 'C:\' survives
    if "::" in s:
        left, right = s.rsplit("::", 1)
        tag = right.lower().strip()
        if tag == "r" or tag == "d-1":
            depth = None
        elif tag.startswith("d"):
            try:
                n = int(tag[1:])
                depth = None if n < 0 else n
            except Exception:
                pass
        s = left
    return (s, depth)


def _expand_glob(pattern: str) -> List[Path]:
    """
    Expand a directory pattern using glob. If no matches, return [pattern] so we can error later.
    """
    matches = [Path(p) for p in glob.glob(pattern)]
    return matches or [Path(pattern)]


def _walk_dirs_up_to(root: Path, max_depth: Optional[int]) -> Iterable[Path]:
    """
    Yield directories to scan honoring max_depth:
      None -> unlimited (yield root itself; pipeline will recurse)
      0    -> just root
      N>0  -> root and all subdirs within distance <= N
    """
    if max_depth is None:
        yield root
        return
    if max_depth == 0:
        if root.is_dir():
            yield root
        return

    # BFS up to depth N
    if not root.is_dir():
        return
    yield root
    cur: List[Path] = [root]
    for _ in range(max_depth):
        nxt: List[Path] = []
        for d in cur:
            try:
                for child in d.iterdir():
                    if child.is_dir():
                        yield child
                        nxt.append(child)
            except Exception:
                continue
        cur = nxt
        if not cur:
            break


# -------- CLI parsing --------

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Find and remove duplicate/similar videos & files using a staged pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Directories (positional; 0+ so that --apply-report works without any)
    p.add_argument(
        "directories",
        nargs="*",
        help=(
            "One or more root directories to scan. "
            "You can add a depth suffix per root like 'DIR::d0' (no recursion), 'DIR::d1', 'DIR::d2', or 'DIR::r' (unlimited). "
            "Globs are supported and are expanded before scanning (e.g. '.\\stars\\*::d0')."
        ),
    )

    # Core scan options
    p.add_argument("-p", "--pattern", action="append", help="Glob to include (repeatable), e.g. -p *.mp4 -p *.mkv")
    p.add_argument("-r", "--recursive", action="store_true", help="Recurse into subdirectories (unlimited) for roots without a ::dN or ::r suffix. Default: no recursion (depth 0)")

    # Quality levels and pipeline selection
    p.add_argument(
        "-Q", "--quality",
        type=str, default="2",
        help=(
            "Quality/thoroughness level or pipeline stages (default: 2): "
            "Quality levels: 1=Size only, 2=Size+hash, 3=Size+hash+metadata, 4=Size+hash+metadata+pHash, 5=All+subset detect. "
            "Pipeline stages: 1, 1-2, 1-3, 1-4, etc. (e.g., '1-3' runs stages 1 through 3)"
        )
    )

    # Output folder (replaces individual -C, -R, -S, -N arguments)
    p.add_argument("-O", "--output-dir", type=str,
                   help="Directory for all outputs (cache, reports, logs). If not specified, writes to current directory.")

    # Performance
    p.add_argument("-t", "--threads", type=int, default=8,
                   help="Worker threads (default: 8)")
    p.add_argument("-g", "--gpu", action="store_true",
                   help="Use GPU acceleration for pHash extraction (requires compatible GPU)")

    # UI
    p.add_argument("-L", "--live", action="store_true", help="Show live progress UI")

    # Logging options
    p.add_argument("--log-level", type=str, default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                   help="File logging level (default: INFO)")
    p.add_argument("--console-log-level", type=str, default="WARNING",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                   help="Console logging level (default: WARNING)")
    p.add_argument("--no-log-file", action="store_true",
                   help="Disable file logging (console only)")

    # Report utilities
    p.add_argument("-P", "--print-report", action="append", help="Path to a JSON report to pretty-print (repeatable)")
    p.add_argument("-V", "--verbosity", type=int, default=1, choices=[0, 1, 2], help="Report/apply verbosity (0–2). Default: 1")
    p.add_argument("-X", "--exclude-by-report", action="append", help="Path to a JSON report; losers listed will be skipped during scan (repeatable)")

    # Report analysis
    p.add_argument("-Y", "--analyze-report", action="append", help="Path to a JSON report to analyze (winner<->loser diffs). Repeatable.")

    # Apply report
    p.add_argument("-A", "--apply-report", type=str, help="Read a JSON report and delete/move all listed losers")
    p.add_argument("-b", "--backup", type=str, help="Move losers to this folder instead of deleting (apply-report mode)")
    p.add_argument("-f", "--force", action="store_true", help="Do not prompt for deletion (apply-report mode)")
    p.add_argument("-x", "--dry-run", action="store_true", help="No changes; just print / write report")

    # Advanced options (moved to subgroup)
    advanced = p.add_argument_group('advanced options', 'Fine-tune detection parameters')
    advanced.add_argument("--duration-tolerance", type=float, default=2.0,
                         help="Duration tolerance in seconds for metadata grouping (default: 2.0)")
    advanced.add_argument("--phash-frames", type=int, default=5,
                         help="Number of frames to sample for perceptual hash comparison (default: 5)")
    advanced.add_argument("--phash-threshold", type=int, default=12,
                         help="Per-frame Hamming distance threshold for pHash matching (default: 12)")
    advanced.add_argument("--subset-min-ratio", type=float, default=0.30,
                         help="Minimum duration ratio (short/long) for subset detection (default: 0.30)")

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
        text = render_analysis_for_reports(paths, verbosity=1, show_progress=True)
        print(text)
        return 0
    return None


def _quality_to_pipeline(quality: str) -> str:
    """Convert quality level to pipeline stages or return pipeline directly."""
    # If it's already a pipeline specification (contains digits and dash), return as-is
    if "-" in quality and all(c.isdigit() or c == "-" for c in quality):
        return quality

    # Map quality levels to pipeline stages first
    quality_map = {
        "1": "1",
        "2": "1-2",
        "3": "1-3",
        "4": "1-4",
        "5": "1-4"  # Level 5 enables subset detection via config
    }

    # If it's a known quality level, return the mapped pipeline
    if quality in quality_map:
        return quality_map[quality]

    # If it's a single digit that's not a quality level, return as-is (for direct stage specs)
    if quality.isdigit():
        return quality

    # Default fallback
    return "1-2"


def _validate_args(args: argparse.Namespace) -> Optional[str]:
    """
    Validate parsed command line arguments.

    Returns:
        Error message string if validation fails, None if validation passes
    """
    # Convert and validate quality level
    try:
        pipeline_str = _quality_to_pipeline(args.quality)
        stages = parse_pipeline(pipeline_str)
        if not stages:
            return f"Invalid quality level: {args.quality}"
    except Exception:
        return f"Failed to parse quality level '{args.quality}'. Use levels 1-5."

    # Validate thread count
    if args.threads <= 0:
        return "Thread count must be positive"

    if args.threads > 64:  # Reasonable upper limit
        return "Thread count seems excessive (>64). Consider reducing for better performance"

    # Validate tolerance values
    duration_tolerance = getattr(args, 'duration_tolerance', 2.0)
    if duration_tolerance < 0:
        return "Duration tolerance must be non-negative"
    if duration_tolerance > 3600:  # 1 hour seems excessive
        return "Duration tolerance seems excessive (>1 hour). Consider reducing"

    # Validate pHash parameters
    phash_frames = getattr(args, 'phash_frames', 5)
    if phash_frames <= 0:
        return "pHash frames count must be positive"

    if phash_frames > 50:  # Reasonable upper limit
        return "pHash frames count seems excessive (>50). Consider reducing for performance"

    phash_threshold = getattr(args, 'phash_threshold', 12)
    subset_min_ratio = getattr(args, 'subset_min_ratio', 0.30)
    if phash_threshold < 0:
        return "pHash threshold must be non-negative"

    if phash_threshold > 64:  # Maximum possible Hamming distance for 64-bit hash
        return "pHash threshold too high (>64). Maximum is 64 for 64-bit hashes"

    # Validate subset detection parameters
    if subset_min_ratio <= 0 or subset_min_ratio >= 1:
        return "Subset minimum ratio must be between 0 and 1 (exclusive)"

    # Validate file paths that must exist
    if args.apply_report:
        report_path = Path(args.apply_report).expanduser().resolve()
        if not report_path.exists():
            return f"Report file not found: {report_path}"
        if not report_path.is_file():
            return f"Report path is not a file: {report_path}"

    if args.exclude_by_report:
        for report in args.exclude_by_report:
            report_path = Path(report).expanduser().resolve()
            if not report_path.exists():
                return f"Exclusion report file not found: {report_path}"

    if args.print_report:
        for report in args.print_report:
            report_path = Path(report).expanduser().resolve()
            if not report_path.exists():
                return f"Report file not found: {report_path}"

    if args.analyze_report:
        for report in args.analyze_report:
            report_path = Path(report).expanduser().resolve()
            if not report_path.exists():
                return f"Report file not found: {report_path}"

    # Validate output directories can be created
    if getattr(args, 'backup', None):
        try:
            backup_path = Path(args.backup).expanduser().resolve()
            backup_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return f"Cannot create backup directory: {e}"

    if getattr(args, 'output_dir', None):
        try:
            output_path = Path(args.output_dir).expanduser().resolve()
            output_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return f"Cannot create output directory: {e}"

    # Validate directory arguments exist (for scan mode)
    if args.directories:
        for directory in args.directories:
            # Parse the directory spec to get the actual path
            dir_spec, _ = _parse_dir_spec(directory, None)
            for expanded_path in _expand_glob(dir_spec):
                if not expanded_path.exists():
                    return f"Directory not found: {expanded_path}"
                if not expanded_path.is_dir():
                    return f"Path is not a directory: {expanded_path}"

    # Validate quality level enables required features
    if args.quality in ["4", "5"] and 4 not in stages:
        return "Quality levels 4 and 5 require pHash stage to be available"

    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    # Global quit flag for signal handling
    quit_requested = False
    active_reporter = None

    # Set up signal handling for proper Ctrl+C behavior
    def signal_handler(sig, frame):
        nonlocal quit_requested, active_reporter
        quit_requested = True
        print("\n\nInterrupted by user. Shutting down gracefully...", file=sys.stderr)
        if active_reporter:
            try:
                active_reporter._quit_evt.set()
                active_reporter.flush()
            except Exception:
                pass
        # Give threads a moment to clean up
        import threading
        import time
        time.sleep(0.5)
        # Force exit if threads don't respond
        print("Forcing exit...", file=sys.stderr)
        sys.exit(1)

    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, signal_handler)

    args = parse_args(argv)

    # Validate arguments
    validation_error = _validate_args(args)
    if validation_error:
        print(f"video-dedupe: error: {validation_error}", file=sys.stderr)
        return 2

    # Setup output directory and logging
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Setup logging
    log_file = None if args.no_log_file else output_dir / f"vdedup-q{args.quality}.log"
    logger = _setup_logging(log_file, args.log_level, args.console_log_level)

    logger.info(f"vdedup started with args: {' '.join(sys.argv[1:])}")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Quality level: {args.quality}")
    if log_file:
        logger.info(f"Logging to: {log_file}")

    # If they only want to print/analyze reports, do that and exit
    maybe = _maybe_print_or_analyze(args)
    if maybe is not None:
        logger.info("Print/analyze mode completed")
        return maybe

    # APPLY REPORT mode
    if args.apply_report:
        logger.info(f"Starting APPLY REPORT mode: {args.apply_report}")
        logger.info(f"Dry run: {args.dry_run}, Force: {args.force}")

        banner = _banner_text(False, dry=args.dry_run, mode="apply", threads=args.threads, gpu=False, backup=getattr(args, 'backup', None))
        # Simplified: always disable UI to prevent freezing issues
        reporter = ProgressReporter(enable_dash=False, refresh_rate=0.2, banner=banner, stacked_ui=None)
        active_reporter = reporter
        reporter.start()
        try:
            report_path = Path(args.apply_report).expanduser().resolve()
            logger.info(f"Report path: {report_path}")

            if not report_path.exists():
                logger.error(f"Report not found: {report_path}")
                print(f"video-dedupe: error: report not found: {report_path}", file=sys.stderr)
                return 2

            # optional base (used only for --backup relative layout)
            base_root: Optional[Path] = None
            if args.directories:
                # when multiple directories are provided, compute a common base for backup layout
                try:
                    base_root = Path(os.path.commonpath([str(Path(d).expanduser().resolve().absolute()) for d in args.directories]))
                    logger.info(f"Base root for backup: {base_root}")
                except Exception as e:
                    logger.warning(f"Could not compute base root: {e}")
                    base_root = None

            backup = Path(args.backup).expanduser().resolve() if getattr(args, 'backup', None) else None
            if backup:
                logger.info(f"Backup directory: {backup}")

            vault = None  # Vault functionality removed
            logger.info("Starting report application...")

            count, size = apply_report(
                report_path,
                dry_run=args.dry_run,
                force=args.force,
                backup=backup,
                base_root=base_root,
                vault=vault,
                reporter=reporter,
                verbosity=int(args.verbosity),
                full_file_names=False,
            )

            reporter.set_results(dup_groups=0, losers_count=count, bytes_total=size)
            result_msg = f"Report applied: removed/moved={count}; size={size/1_048_576:.2f} MiB"
            logger.info(result_msg)
            print(result_msg)
            return 0
        except Exception as e:
            logger.error(f"Error applying report: {e}")
            raise
        finally:
            reporter.stop()
            logger.info("Apply report mode completed")

    # SCAN mode
    if not args.directories:
        logger.error("No directories specified for scanning")
        print("video-dedupe: error: the following arguments are required: one or more directories (or use -P/--print-report / -Y/--analyze-report)", file=sys.stderr)
        return 2

    logger.info(f"Starting SCAN mode for directories: {args.directories}")

    # Build (pattern, depth) per root, expand globs
    default_depth: Optional[int] = None if args.recursive else 0
    parsed_specs: List[Tuple[Path, Optional[int]]] = []
    for spec in args.directories:
        logger.debug(f"Parsing directory spec: {spec}")
        pat, depth = _parse_dir_spec(spec, default_depth)
        for match in _expand_glob(pat):
            resolved_path = match.expanduser().resolve()
            parsed_specs.append((resolved_path, depth))
            logger.debug(f"Added directory: {resolved_path} (depth: {depth})")

    logger.info(f"Total directories to scan: {len(parsed_specs)}")

    # Validate existence (pre-expansion will yield a concrete list)
    for r, _d in parsed_specs:
        if not r.exists():
            logger.error(f"Directory not found: {r}")
            print(f"video-dedupe: error: directory not found: {r}", file=sys.stderr)
            return 2

    patterns = _normalize_patterns(args.pattern)
    logger.info(f"File patterns: {patterns or 'all files'}")

    # Convert quality level to pipeline stages
    pipeline_str = _quality_to_pipeline(args.quality)
    logger.info(f"Pipeline stages: {pipeline_str}")

    # Auto-generate cache and report filenames
    base_name = f"vdedup-q{args.quality}"
    cache_path = output_dir / f"{base_name}-cache.jsonl"
    report_path = output_dir / f"{base_name}-report.json"
    logger.info(f"Cache file: {cache_path}")
    logger.info(f"Report file: {report_path}")

    cfg = PipelineConfig(
        threads=max(1, int(args.threads)),
        duration_tolerance=getattr(args, 'duration_tolerance', 2.0),
        same_res=False,
        same_codec=False,
        same_container=False,
        phash_frames=getattr(args, 'phash_frames', 5),
        phash_threshold=getattr(args, 'phash_threshold', 12),
        subset_detect=(args.quality == "5"),  # Enable subset detection for quality level 5
        subset_min_ratio=getattr(args, 'subset_min_ratio', 0.30),
        subset_frame_threshold=max(getattr(args, 'phash_threshold', 12), 12),
        gpu=bool(args.gpu),
    )

    logger.info(f"Pipeline configuration: threads={cfg.threads}, GPU={cfg.gpu}, subset_detect={cfg.subset_detect}")
    logger.debug(f"Advanced config: duration_tolerance={cfg.duration_tolerance}, phash_frames={cfg.phash_frames}, phash_threshold={cfg.phash_threshold}")

    banner = _banner_text(True, dry=args.dry_run, mode=f"Q{args.quality}", threads=cfg.threads, gpu=cfg.gpu, backup=getattr(args, 'backup', None))

    # Inform user if they requested UI mode
    if args.live:
        print("Note: Live UI (-L) is temporarily disabled for stability. Running in console mode.")
        logger.info("User requested live UI (-L) but running in console mode for stability")

    logger.info("Creating ProgressReporter...")
    # Simplified: always disable UI to prevent freezing issues
    reporter = ProgressReporter(enable_dash=False, refresh_rate=0.2, banner=banner, stacked_ui=None)
    active_reporter = reporter
    logger.info("Starting ProgressReporter...")
    reporter.start()
    logger.info("ProgressReporter started successfully")

    logger.info("Initializing hash cache...")
    cache = HashCache(cache_path)
    cache.open_append()

    # Build exclusion set from reports, if any
    skip_paths = set()
    if args.exclude_by_report:
        logger.info(f"Processing exclusion reports: {args.exclude_by_report}")
        ex_paths = [Path(p).expanduser().resolve() for p in args.exclude_by_report]
        skip_paths = collect_exclusions(ex_paths)
        if skip_paths:
            logger.info(f"Excluding {len(skip_paths)} files from previous reports")
            print(f"Excluding {len(skip_paths)} files listed as losers in supplied report(s).")

    try:
        logger.info(f"Parsing pipeline stages: {pipeline_str}")
        stages = parse_pipeline(pipeline_str)
        logger.info(f"Active pipeline stages: {[s for s in stages]}")

        # Partition roots into: unlimited-depth batch (max_depth=None) and finite-depth batches expanded into max_depth=0
        unlimited_roots: List[Path] = []
        finite_expanded_roots: List[Path] = []
        for root, depth in parsed_specs:
            for d in _walk_dirs_up_to(root, depth):
                # If depth is None (unlimited) and d==root, keep in unlimited bucket;
                # otherwise we expand into finite list scanned at depth 0.
                if depth is None and d == root:
                    unlimited_roots.append(d)
                    logger.debug(f"Unlimited depth root: {d}")
                else:
                    finite_expanded_roots.append(d)
                    logger.debug(f"Finite depth root: {d}")

        logger.info(f"Unlimited depth roots: {len(unlimited_roots)}")
        logger.info(f"Finite depth roots: {len(finite_expanded_roots)}")

        groups_all: Dict[str, Tuple[Any, List[Any]]] = {}

        def _merge_groups(dst: Dict[str, Tuple[Any, List[Any]]], src: Dict[str, Tuple[Any, List[Any]]]):
            # Avoid accidental key collisions by rewriting ids if necessary
            for k, v in src.items():
                nk = k
                i = 1
                while nk in dst and dst[nk] is not v:
                    nk = f"{k}#{i}"
                    i += 1
                dst[nk] = v

        # Run unlimited batch (if any)
        if unlimited_roots:
            logger.info(f"Running unlimited depth pipeline on {len(unlimited_roots)} roots...")
            try:
                # Simplified approach: always use non-UI reporter for pipeline execution
                pipeline_reporter = ProgressReporter(enable_dash=False)
                g_unlim = run_pipeline(
                    roots=unlimited_roots,
                    patterns=patterns,
                    max_depth=None,
                    selected_stages=stages,
                    cfg=cfg,
                    cache=cache,
                    reporter=pipeline_reporter,
                    skip_paths=skip_paths,
                )
                logger.info(f"Unlimited depth pipeline completed with {len(g_unlim)} groups")
            except TypeError as e:
                logger.warning(f"Multiple roots not supported by current pipeline, falling back to single root: {e}")
                # Fallback: if multiple, try common parent; else first
                common: Optional[Path] = None
                try:
                    common = Path(os.path.commonpath([str(r) for r in unlimited_roots]))
                except Exception:
                    common = None
                root = common if common and common.exists() else unlimited_roots[0]
                logger.info(f"Using fallback root: {root}")
                if len(unlimited_roots) > 1 and (common is None or common not in unlimited_roots):
                    warning_msg = "Warning: current pipeline doesn't accept multiple roots; running on the first directory only for unlimited-depth set. Cross-root duplicates may be missed."
                    logger.warning(warning_msg)
                    print(warning_msg, file=sys.stderr)
                # Simplified approach: always use non-UI reporter for pipeline execution
                pipeline_reporter = ProgressReporter(enable_dash=False)
                g_unlim = run_pipeline(
                    root=root,
                    patterns=patterns,
                    max_depth=None,
                    selected_stages=stages,
                    cfg=cfg,
                    cache=cache,
                    reporter=pipeline_reporter,
                    skip_paths=skip_paths,
                )
                logger.info(f"Fallback unlimited depth pipeline completed with {len(g_unlim)} groups")
            _merge_groups(groups_all, g_unlim)

        # Run finite-expanded batch in one go at depth=0 (if any)
        if finite_expanded_roots:
            logger.info(f"Running finite depth pipeline on {len(finite_expanded_roots)} roots...")
            try:
                # Simplified approach: always use non-UI reporter for pipeline execution
                pipeline_reporter = ProgressReporter(enable_dash=False)
                g_fin = run_pipeline(
                    roots=finite_expanded_roots,
                    patterns=patterns,
                    max_depth=0,
                    selected_stages=stages,
                    cfg=cfg,
                    cache=cache,
                    reporter=pipeline_reporter,
                    skip_paths=skip_paths,
                )
                logger.info(f"Finite depth pipeline completed with {len(g_fin)} groups")
            except TypeError as e:
                logger.warning(f"Multiple roots not supported by current pipeline, falling back to single root: {e}")
                # Fallback: try common parent
                common: Optional[Path] = None
                try:
                    common = Path(os.path.commonpath([str(r) for r in finite_expanded_roots]))
                except Exception:
                    common = None
                root = common if common and common.exists() else finite_expanded_roots[0]
                logger.info(f"Using fallback root for finite depth: {root}")
                if len(finite_expanded_roots) > 1 and (common is None or common not in finite_expanded_roots):
                    warning_msg = "Warning: pipeline doesn't accept multiple roots; running on the first directory only for finite-depth set. Cross-root duplicates may be missed."
                    logger.warning(warning_msg)
                    print(warning_msg, file=sys.stderr)

                logger.info("Starting run_pipeline call...")

                # Simplified approach: always use non-UI reporter for pipeline execution
                # This prevents all threading and UI conflicts
                pipeline_reporter = ProgressReporter(enable_dash=False)
                g_fin = run_pipeline(
                    root=root,
                    patterns=patterns,
                    max_depth=0,
                    selected_stages=stages,
                    cfg=cfg,
                    cache=cache,
                    reporter=pipeline_reporter,
                    skip_paths=skip_paths,
                )

                logger.info(f"Fallback finite depth pipeline completed with {len(g_fin)} groups")
            _merge_groups(groups_all, g_fin)

        logger.info(f"Total groups found: {len(groups_all)}")
        logger.info("Choosing winners from duplicate groups...")
        keep_order = ["longer", "resolution", "video-bitrate", "newer", "smaller", "deeper"]
        winners = choose_winners(groups_all, keep_order)

        logger.info(f"Writing report with {len(winners)} groups to: {report_path}")
        write_report(report_path, winners)
        print(f"Wrote report to: {report_path}")

        losers = [loser for (_keep, losers) in winners.values() for loser in losers]
        bytes_total = sum(int(getattr(l, "size", 0)) for l in losers)
        logger.info(f"Final results: {len(winners)} duplicate groups, {len(losers)} losers, {_fmt_bytes(bytes_total)} reclaimable")
        reporter.set_results(dup_groups=len(winners), losers_count=len(losers), bytes_total=bytes_total)

        # If they also passed -P or -Y with directories, run those too (after scan)
        if args.print_report:
            logger.info(f"Pretty printing reports: {args.print_report}")
            paths = [Path(p).expanduser().resolve() for p in args.print_report]
            print(pretty_print_reports(paths, verbosity=int(args.verbosity)))
        if args.analyze_report:
            logger.info(f"Analyzing reports: {args.analyze_report}")
            paths = [Path(p).expanduser().resolve() for p in args.analyze_report]
            print(render_analysis_for_reports(paths, verbosity=1, show_progress=True))

        logger.info("Scan mode completed successfully")
        return 0
    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}")
        raise
    finally:
        if cache:
            logger.debug("Closing hash cache")
            cache.close()
        reporter.stop()
        logger.info("vdedup session ended")


if __name__ == "__main__":
    sys.exit(main())
