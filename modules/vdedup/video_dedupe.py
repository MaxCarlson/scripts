#!/usr/bin/env python3
"""
vdedup.video_dedupe – CLI entrypoint

This CLI drives the staged pipeline and report application.

Subcommands:

  video-dedupe scan  [scan args]   – Scan directories for duplicates
  video-dedupe view  [view args]   – View / analyze existing reports
  video-dedupe apply [apply args]  – Apply a report (delete/move losers)

Examples:

  # Fast exact-dupe sweep (HDD-friendly)
  video-dedupe scan -D "D:\\Videos" -q 2 -p *.mp4 -r -t 4 -o D:\\output -L

  # Thorough scan including pHash + subset detection
  video-dedupe scan -D "D:\\Videos" -q 5 -u 8 -F 9 -T 14 -t 16 -o D:\\output -L -g

  # Scan seeded from a previous report + 3 random extras per group
  video-dedupe scan -D "D:\\Videos" -q 2 -R D:\\prev.json -J 3 -E 42 -o D:\\output

  # Apply a previously generated report
  video-dedupe apply -a D:\\report.json -f -b D:\\Quarantine

  # Print / analyze reports
  video-dedupe view -P D:\\report.json -v 2
  video-dedupe view -y D:\\report.json
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import random
import re
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# Import EnforcedArgumentParser
try:
    from argparse_enforcer import EnforcedArgumentParser

    ENFORCER_AVAILABLE = True
except ImportError:
    EnforcedArgumentParser = argparse.ArgumentParser
    ENFORCER_AVAILABLE = False

# NOTE: absolute imports so the CLI works whether installed or run from source
from vdedup.gpu_capabilities import validate_gpu_mode as _validate_gpu_mode
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
)
from vdedup.report_viewer import launch_report_viewer

_LOCK_STALE_SECONDS = 24 * 3600


def _lock_owner_pid(lock_file: Path) -> Optional[int]:
    try:
        content = lock_file.read_text().splitlines()
        if content:
            pid = int(content[0])
            return pid if pid > 0 else None
    except Exception:
        return None
    return None


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)  # type: ignore[attr-defined]
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _acquire_output_lock(lock_file: Path, *, resume: bool, logger: logging.Logger) -> bool:
    """
    Try to create the output lock file. Returns True on success, False if another
    run appears active and resume flag was not supplied.
    """
    if lock_file.exists():
        lock_age = time.time() - lock_file.stat().st_mtime
        owner_pid = _lock_owner_pid(lock_file)
        if owner_pid and not _pid_is_running(owner_pid):
            logger.warning("Removing lock held by inactive PID %s: %s", owner_pid, lock_file)
            try:
                lock_file.unlink()
            except Exception as exc:
                logger.error("Failed removing stale PID lock: %s", exc)
                return False
            lock_age = 0
        if resume:
            logger.info("Resuming run; removing existing lock at %s", lock_file)
            try:
                lock_file.unlink()
            except Exception as exc:
                logger.error("Failed removing existing lock: %s", exc)
                return False
        elif lock_age >= _LOCK_STALE_SECONDS:
            logger.warning("Removing stale lock file (age %.1fh): %s", lock_age / 3600, lock_file)
            try:
                lock_file.unlink()
            except Exception as exc:
                logger.error("Failed removing stale lock: %s", exc)
                return False
        else:
            return False

    lock_file.write_text(f"{os.getpid()}\n{time.time()}\n")
    logger.info(f"Created lock file: {lock_file}")
    return True


def _release_output_lock(lock_file: Path, logger: logging.Logger) -> None:
    if lock_file.exists():
        try:
            lock_file.unlink()
            logger.debug(f"Removed lock file: {lock_file}")
        except Exception as exc:
            logger.warning(f"Failed to remove lock file: {exc}")


# -------- helpers --------


def _default_thread_count() -> int:
    """
    Return an auto-tuned default thread count (cores minus four) with a floor of one.
    This keeps a few logical CPUs free for the OS / GPU drivers on heavily threaded hosts.
    """
    max_threads = os.cpu_count() or 8
    return max(1, max_threads - 4)


def _infer_quality_level(value: Optional[str]) -> int:
    """
    Convert the CLI quality string into an approximate numeric level.
    Accepts presets like '5' as well as explicit pipelines like '1-6'.
    """
    if not value:
        return 2
    digits = [int(m) for m in re.findall(r"\d+", value)]
    if digits:
        return max(digits)
    return 2


def _quality_default_config(quality: Optional[str]) -> Dict[str, Any]:
    """
    Build adaptive defaults for the advanced detection knobs based on the requested quality.
    Higher quality levels sample more frames, tighten thresholds, and widen duration tolerances
    per the guidance captured in DETAILED_RESEARCH.md (10% overlap and thorough-mode sampling).
    """
    level = _infer_quality_level(quality)
    defaults: Dict[str, Any] = {
        "duration_tolerance": 2.0,
        "phash_frames": 5,
        "phash_threshold": 12,
        "subset_min_ratio": 0.10,
        "include_partials": False,
    }
    if level >= 4:
        defaults.update(
            {
                "duration_tolerance": 3.0,
                "phash_frames": 12,
                "phash_threshold": 11,
                "subset_min_ratio": 0.12,
            }
        )
    if level >= 5:
        defaults.update(
            {
                "duration_tolerance": 4.0,
                "phash_frames": 16,
                "phash_threshold": 10,
                "subset_min_ratio": 0.09,
            }
        )
    if level >= 6:
        defaults.update(
            {
                "duration_tolerance": 5.0,
                "phash_frames": 20,
                "phash_threshold": 9,
                "subset_min_ratio": 0.08,
                "include_partials": True,
            }
        )
    if level >= 7:
        defaults.update(
            {
                "duration_tolerance": 6.0,
                "phash_frames": 24,
                "phash_threshold": 9,
                "subset_min_ratio": 0.07,
            }
        )
    return defaults


def _apply_quality_defaults(args: argparse.Namespace) -> None:
    """Fill in adaptive defaults for CLI arguments after parsing."""
    defaults = _quality_default_config(getattr(args, "quality", None))
    for field, value in defaults.items():
        current = getattr(args, field, None)
        if current is None:
            setattr(args, field, value)
    if getattr(args, "threads", None) is None:
        args.threads = _default_thread_count()


def _normalize_patterns(patts: Optional[List[str]]) -> Optional[List[str]]:
    if not patts:
        return None
    out: List[str] = []
    seen: set[str] = set()
    for p in patts:
        s = (p or "").strip()
        if not s:
            continue
        if not any(ch in s for ch in "*?["):
            s = f"*.{s.lstrip('.')}"
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(key)  # Append lowercased version for consistency
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


def _setup_logging(
    log_file: Optional[Path] = None, log_level: str = "INFO", console_level: str = "WARNING"
) -> logging.Logger:
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
    logger = logging.getLogger("vdedup")
    logger.setLevel(logging.DEBUG)  # Capture everything, filter at handler level

    # Clear any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # File handler (detailed logging)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        file_handler.setLevel(getattr(logging, log_level.upper()))

        # Detailed format for file
        file_format = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(funcName)-20s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

    # Console handler (less verbose)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(getattr(logging, console_level.upper()))

    # Simple format for console
    console_format = logging.Formatter("%(levelname)s: %(message)s")
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
            sys.stdout.write(
                f"{self.label} [{'#'*filled}{'-'*(barw - filled)}] {self.n}/{self.total}  {pct*100:5.1f}%  ETA {self._fmt_hms(eta)}"
            )
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
            for loser in losers:
                total_pairs += 1
                a = _probe_stats(keep)
                b = _probe_stats(loser)
                # If report summary didn't contain size_bytes, accumulate via probing
                if not isinstance(data.get("summary"), dict) or "size_bytes" not in data["summary"]:
                    try:
                        overall_space_bytes += int(b.get("size") or 0)
                    except Exception:
                        pass
                if verbosity >= 1:
                    out.extend(f"    {line}" for line in _render_pair_diff(keep, loser, a, b))
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


# ========================
# Report-seeded scan helper
# ========================


def _build_seed_include_paths(
    seed_report: Path,
    parsed_specs: List[Tuple[Path, Optional[int]]],
    patterns: Optional[List[str]],
    exclude_patterns: Optional[List[str]],
    seed_random_per_group: int,
    sample_seed: Optional[int],
    skip_paths: Set[Path],
    logger: logging.Logger,
) -> Optional[Set[Path]]:
    """
    Build the include_paths set for a report-seeded scan.

    Mandatory paths: keep + losers from every group in seed_report that exist on disk.
    Random extras: up to seed_random_per_group * group_count additional files drawn
    uniformly from the scan directories (excluding mandatory paths and skip_paths).
    """
    from vdedup.pipeline import _iter_files as _piter  # private but package-internal

    data = load_report(seed_report)
    groups = data.get("groups") or {}
    group_count = len(groups)

    mandatory: Set[Path] = set()
    for g in groups.values():
        keep_str = g.get("keep", "")
        if keep_str:
            p = Path(keep_str).expanduser().resolve()
            if p.exists():
                mandatory.add(p)
        for loser_str in (g.get("losers") or []):
            p = Path(loser_str).expanduser().resolve()
            if p.exists():
                mandatory.add(p)

    logger.info("Seed report: %d groups, %d mandatory paths", group_count, len(mandatory))

    if seed_random_per_group <= 0 or group_count == 0:
        return mandatory if mandatory else None

    # Discover candidate files for random selection (exclude mandatory + skip_paths)
    skip_norm = {p.expanduser().resolve() for p in skip_paths}
    candidates: List[Path] = []
    for root_dir, depth in parsed_specs:
        for f in _piter(root_dir, patterns, depth, exclude_patterns):
            resolved = f.expanduser().resolve()
            if resolved not in mandatory and resolved not in skip_norm:
                candidates.append(resolved)

    n_random = seed_random_per_group * group_count
    seed = sample_seed if sample_seed is not None else time.time()
    rng = random.Random(seed)
    # Sort for determinism before sampling
    candidates_sorted = sorted(candidates)
    extras: Set[Path] = set(rng.sample(candidates_sorted, min(len(candidates_sorted), n_random)))

    logger.info(
        "Seed random: %d requested (%d/group × %d groups), %d available, %d selected",
        n_random, seed_random_per_group, group_count, len(candidates_sorted), len(extras),
    )
    return mandatory | extras


# -------- CLI parsing --------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="video-dedupe",
        description="Find and remove duplicate/similar videos & files using a staged pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subs = p.add_subparsers(dest="command", metavar="COMMAND")
    subs.required = True

    # ---- scan subcommand ----
    # All scan-relevant args live here; nothing is inherited from a shared parent.
    threads_default = _default_thread_count()
    scan_p = subs.add_parser(
        "scan",
        help="Scan directories for duplicate files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Directories & patterns
    scan_p.add_argument(
        "-D", "--directory", action="append", dest="directories",
        help=(
            "Root directory to scan (repeatable). "
            "Supports DIR::dN depth suffixes and globs."
        ),
    )
    scan_p.add_argument(
        "-p", "--pattern", action="append", default=["*.mp4"],
        help="Glob to include (repeatable, default: *.mp4).",
    )
    scan_p.add_argument("-X", "--exclude-pattern", action="append", help="Glob to exclude (repeatable).")
    scan_p.add_argument(
        "-r", "--recursive", action="store_true",
        help="Recurse into subdirectories (unlimited) for roots without a ::dN suffix.",
    )
    # Quality / pipeline
    scan_p.add_argument(
        "-q", "--quality", type=str, default="2",
        help=(
            "Stage selector (default: 2): "
            "1=size, 2=hash, 3=metadata, 4=pHash, 5=scene, 6=audio, 7=timeline. "
            "Use ranges like 1-2 or 1-5 to combine stages."
        ),
    )
    # Seed-report scan
    scan_p.add_argument(
        "-R", "--seed-report", type=str,
        help="Load an existing report and force all keep+loser paths into the scan set.",
    )
    scan_p.add_argument(
        "-J", "--seed-random-per-group", type=int, default=0,
        help="Add up to N extra random files per group from the scan dirs. Requires -R/--seed-report.",
    )
    # Sampling & limits
    scan_p.add_argument(
        "-m", "--sample-percent", type=float, default=None,
        help="Randomly sample this percentage (0-100] of discovered files.",
    )
    scan_p.add_argument(
        "-E", "--sample-seed", type=int, default=None,
        help="Deterministic seed for --sample-percent or --seed-random-per-group.",
    )
    scan_p.add_argument(
        "-N", "--max-duplicates", type=int, default=None,
        help="Stop after finding at least this many duplicate loser files.",
    )
    # Exclusions
    scan_p.add_argument(
        "-e", "--exclude-by-report", action="append",
        help="Report whose losers are skipped during scan (repeatable).",
    )
    # Behaviour flags
    scan_p.add_argument("-d", "--dry-run", action="store_true", help="Do not write report; just print findings.")
    scan_p.add_argument(
        "-g", "--gpu",
        type=_validate_gpu_mode,
        default="auto",
        metavar="{auto,on,off}",
        help="GPU route mode: auto (use if available), on (require GPU), off (force CPU). Default: auto.",
    )
    scan_p.add_argument(
        "--gpu-device-id",
        type=int,
        default=0,
        help="CUDA device index to use for GPU operations (default: 0).",
    )
    scan_p.add_argument("-L", "--live", action="store_true", help="Show live progress UI.")
    # Output & logging
    scan_p.add_argument(
        "-o", "--output-dir", type=str,
        help="Directory for cache, report, and log files. Defaults to current directory.",
    )
    scan_p.add_argument(
        "-K", "--resume-output", action="store_true",
        help="Resume a previous run by removing the .vdedup.lock in the output directory.",
    )
    scan_p.add_argument(
        "-l", "--log-level", type=str, default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="File logging level (default: INFO).",
    )
    scan_p.add_argument(
        "-c", "--console-log-level", type=str, default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Console logging level (default: INFO).",
    )
    scan_p.add_argument("-n", "--no-log-file", action="store_true", help="Disable file logging.")
    # Output verbosity and performance (scan-specific)
    scan_p.add_argument(
        "-v", "--verbosity", type=int, default=1, choices=[0, 1, 2],
        help="Output verbosity (0-2, default: 1).",
    )
    scan_p.add_argument(
        "-t", "--threads", type=int, default=threads_default,
        help=f"Worker threads (default: cores-4 → {threads_default}).",
    )
    # Advanced detection options
    adv = scan_p.add_argument_group("advanced options", "Fine-tune detection parameters")
    adv.add_argument(
        "-u", "--duration-tolerance", type=float, default=None,
        help="Duration tolerance in seconds for metadata grouping (quality-aware default).",
    )
    adv.add_argument(
        "-F", "--phash-frames", type=int, default=None,
        help="Number of frames to sample for perceptual hash comparison.",
    )
    adv.add_argument(
        "-T", "--phash-threshold", type=int, default=None,
        help="Per-frame Hamming distance threshold for pHash matching.",
    )
    adv.add_argument(
        "-s", "--subset-min-ratio", type=float, default=None,
        help="Minimum duration ratio (short/long) for subset detection.",
    )
    adv.add_argument(
        "-A", "--include-partials", action="store_true", default=None,
        help="Include partial/incomplete downloads during scan.",
    )

    # ---- view subcommand (read-only; no output dir, no logging, no threads) ----
    view_p = subs.add_parser(
        "view",
        help="View or analyze existing deduplication reports.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    view_p.add_argument(
        "-P", "--print-report", action="append",
        help="Pretty-print a JSON report (repeatable).",
    )
    view_p.add_argument(
        "-V", "--view-report", action="append",
        help="Open a JSON report in the interactive viewer (repeatable).",
    )
    view_p.add_argument(
        "-a", "--analyze-report", action="append",
        help="Show winner<->loser stat diffs for a report (repeatable).",
    )
    view_p.add_argument(
        "-v", "--verbosity", type=int, default=1, choices=[0, 1, 2],
        help="Output verbosity (0-2, default: 1).",
    )

    # ---- apply subcommand ----
    # Intentionally excludes -L/--live (apply always runs non-interactive) and
    # -t/--threads (apply is single-threaded).
    apply_p = subs.add_parser(
        "apply",
        help="Apply a deduplication report (delete or move losers).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    apply_p.add_argument("-a", "--apply-report", type=str, help="Path to the JSON report to apply.")
    apply_p.add_argument("-d", "--dry-run", action="store_true", help="No changes; just print what would happen.")
    apply_p.add_argument("-f", "--force", action="store_true", help="Do not prompt for deletion.")
    apply_p.add_argument("-b", "--backup", type=str, help="Move losers to this folder instead of deleting.")
    apply_p.add_argument(
        "-p", "--folder-priority", type=str,
        help="Move kept files into this folder tree when a duplicate in the group is already there.",
    )
    apply_p.add_argument(
        "-D", "--directory", action="append", dest="directories",
        help="Base directories for relative backup path layout (optional).",
    )
    apply_p.add_argument(
        "-v", "--verbosity", type=int, default=1, choices=[0, 1, 2],
        help="Output verbosity (0-2, default: 1).",
    )
    apply_p.add_argument(
        "-o", "--output-dir", type=str,
        help="Directory for log file. Defaults to current directory.",
    )
    apply_p.add_argument(
        "-K", "--resume-output", action="store_true",
        help="Resume a previous run by removing the .vdedup.lock in the output directory.",
    )
    apply_p.add_argument(
        "-l", "--log-level", type=str, default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="File logging level (default: INFO).",
    )
    apply_p.add_argument(
        "-c", "--console-log-level", type=str, default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Console logging level (default: INFO).",
    )
    apply_p.add_argument("-n", "--no-log-file", action="store_true", help="Disable file logging.")
    apply_p.add_argument(
        "-F", "--force-review-required", action="store_true",
        help="[DEPRECATED — no-op] REVIEW groups are applied automatically when actionable=True.",
    )

    args = p.parse_args(argv)
    if args.command == "scan":
        _apply_quality_defaults(args)
    return args


def _quality_to_pipeline(quality: str) -> str:
    """Convert quality level to pipeline stages or return pipeline directly."""
    # If it's already a pipeline specification (contains digits and dash), return as-is
    if "-" in quality and all(c.isdigit() or c == "-" for c in quality):
        return quality

    # Single digits are direct stage selectors. Use ranges/lists for combined scans.
    if quality.isdigit():
        return quality

    # Default fallback
    return "1-2"


# -------- per-command validators --------


def _validate_scan_args(args: argparse.Namespace) -> Optional[str]:
    try:
        pipeline_str = _quality_to_pipeline(args.quality)
        stages = parse_pipeline(pipeline_str)
        if not stages:
            return f"Invalid quality level: {args.quality}"
    except Exception:
        return f"Failed to parse quality level '{args.quality}'. Use levels 1-5."

    if args.threads <= 0:
        return "Thread count must be positive"
    if args.threads > 64:
        return "Thread count seems excessive (>64). Consider reducing for better performance"

    if getattr(args, "max_duplicates", None) is not None and args.max_duplicates <= 0:
        return "--max-duplicates must be positive"

    if getattr(args, "sample_percent", None) is not None:
        if args.sample_percent <= 0 or args.sample_percent > 100:
            return "--sample-percent must be between 0 and 100"

    duration_tolerance = getattr(args, "duration_tolerance", 2.0)
    if duration_tolerance is not None and duration_tolerance < 0:
        return "Duration tolerance must be non-negative"
    if duration_tolerance is not None and duration_tolerance > 3600:
        return "Duration tolerance seems excessive (>1 hour). Consider reducing"

    phash_frames = getattr(args, "phash_frames", 5)
    if phash_frames is not None and phash_frames <= 0:
        return "pHash frames count must be positive"
    if phash_frames is not None and phash_frames > 50:
        return "pHash frames count seems excessive (>50). Consider reducing for performance"

    phash_threshold = getattr(args, "phash_threshold", 12)
    if phash_threshold is not None and phash_threshold < 0:
        return "pHash threshold must be non-negative"
    if phash_threshold is not None and phash_threshold > 64:
        return "pHash threshold too high (>64). Maximum is 64 for 64-bit hashes"

    subset_min_ratio = getattr(args, "subset_min_ratio", 0.10)
    if subset_min_ratio is not None and (subset_min_ratio <= 0 or subset_min_ratio >= 1):
        return "Subset minimum ratio must be between 0 and 1 (exclusive)"

    # -J/--seed-random-per-group requires -R/--seed-report
    if getattr(args, "seed_random_per_group", 0) and not getattr(args, "seed_report", None):
        return "--seed-random-per-group/-J requires --seed-report/-R to be specified"

    if getattr(args, "seed_report", None):
        rp = Path(args.seed_report).expanduser().resolve()
        if not rp.exists():
            return f"Seed report not found: {rp}"
        if not rp.is_file():
            return f"Seed report is not a file: {rp}"

    if args.exclude_by_report:
        for report in args.exclude_by_report:
            rp = Path(report).expanduser().resolve()
            if not rp.exists():
                return f"Exclusion report file not found: {rp}"

    if getattr(args, "backup", None):
        try:
            backup_path = Path(args.backup).expanduser().resolve()
            backup_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return f"Cannot create backup directory: {e}"

    if getattr(args, "output_dir", None):
        try:
            output_path = Path(args.output_dir).expanduser().resolve()
            output_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return f"Cannot create output directory: {e}"

    if args.directories:
        for directory in args.directories:
            dir_spec, _ = _parse_dir_spec(directory, None)
            for expanded_path in _expand_glob(dir_spec):
                if not expanded_path.exists():
                    return f"Directory not found: {expanded_path}"
                if not expanded_path.is_dir():
                    return f"Path is not a directory: {expanded_path}"

    return None


def _validate_view_args(args: argparse.Namespace) -> Optional[str]:
    has_any = any([
        getattr(args, "print_report", None),
        getattr(args, "view_report", None),
        getattr(args, "analyze_report", None),
    ])
    if not has_any:
        return "view requires at least one of -P/--print-report, -V/--view-report, or -a/--analyze-report"

    for attr in ("print_report", "view_report", "analyze_report"):
        paths_list = getattr(args, attr, None)
        if paths_list:
            for rp_str in paths_list:
                rp = Path(rp_str).expanduser().resolve()
                if not rp.exists():
                    return f"Report file not found: {rp}"
    return None


def _validate_apply_args(args: argparse.Namespace) -> Optional[str]:
    if not getattr(args, "apply_report", None):
        if getattr(args, "folder_priority", None):
            return "--folder-priority can only be used with -a/--apply-report"
        return "-a/--apply-report is required for the apply command"

    rp = Path(args.apply_report).expanduser().resolve()
    if not rp.exists():
        return f"Report file not found: {rp}"
    if not rp.is_file():
        return f"Report path is not a file: {rp}"

    if getattr(args, "backup", None):
        try:
            backup_path = Path(args.backup).expanduser().resolve()
            backup_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return f"Cannot create backup directory: {e}"

    if getattr(args, "output_dir", None):
        try:
            output_path = Path(args.output_dir).expanduser().resolve()
            output_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return f"Cannot create output directory: {e}"

    return None


def _validate_args(args: argparse.Namespace) -> Optional[str]:
    """Dispatch to the appropriate per-subcommand validator."""
    if args.command == "scan":
        return _validate_scan_args(args)
    if args.command == "view":
        return _validate_view_args(args)
    if args.command == "apply":
        return _validate_apply_args(args)
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    # Global quit flag for signal handling
    quit_requested = False
    active_reporter = None

    # Set up signal handling for proper Ctrl+C behavior
    def signal_handler(sig, frame):
        nonlocal quit_requested, active_reporter
        if quit_requested:
            print("\n\nForce quitting...", file=sys.stderr)
            os._exit(1)

        quit_requested = True
        print("\n\n=== Interrupt detected! Shutting down... ===", file=sys.stderr)
        print("(Press Ctrl+C again to force quit)", file=sys.stderr)

        if active_reporter:
            try:
                active_reporter._quit_evt.set()
                active_reporter.add_log("User requested shutdown (Ctrl+C)", "WARNING", source="signals")
                active_reporter.stop()
            except Exception as e:
                print(f"Error during cleanup: {e}", file=sys.stderr)

    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal_handler)

    args = parse_args(argv)

    # Validate arguments
    validation_error = _validate_args(args)
    if validation_error:
        print(f"video-dedupe {args.command}: error: {validation_error}", file=sys.stderr)
        return 2

    # VIEW command — read-only; no output dir, no lock, no file logging needed.
    if args.command == "view":
        logger = _setup_logging(None, "INFO", "WARNING")
        if args.view_report:
            paths = [Path(p).expanduser().resolve() for p in args.view_report]
            launch_report_viewer(paths)
        if args.print_report:
            paths = [Path(p).expanduser().resolve() for p in args.print_report]
            print(pretty_print_reports(paths, verbosity=int(args.verbosity)))
        if args.analyze_report:
            paths = [Path(p).expanduser().resolve() for p in args.analyze_report]
            print(render_analysis_for_reports(paths, verbosity=1, show_progress=True))
        return 0

    # SCAN and APPLY: need output dir, logging, and a lock file.
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)

    log_name = f"vdedup-q{args.quality}.log" if args.command == "scan" else "vdedup-apply.log"
    log_file = None if args.no_log_file else output_dir / log_name
    logger = _setup_logging(log_file, args.log_level, args.console_log_level)

    logger.info("vdedup %s started: %s", args.command, " ".join(sys.argv[1:]))
    logger.info("Output directory: %s", output_dir)

    # scan only: live UI suppresses console logging
    if args.command == "scan" and args.live:
        logger.info("Live UI enabled - suppressing console output")
        for handler in logger.handlers[:]:
            if isinstance(handler, logging.StreamHandler) and handler.stream in (sys.stdout, sys.stderr):
                logger.removeHandler(handler)
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            if isinstance(handler, logging.StreamHandler) and handler.stream in (sys.stdout, sys.stderr):
                root_logger.removeHandler(handler)

    # Acquire lock for scan/apply (stateful operations that modify the output dir)
    lock_file = output_dir / ".vdedup.lock"
    if not _acquire_output_lock(lock_file, resume=bool(args.resume_output), logger=logger):
        print(f"video-dedupe: error: Another vdedup instance is running in {output_dir}", file=sys.stderr)
        print(f"video-dedupe: error: Lock file: {lock_file}", file=sys.stderr)
        print(
            "video-dedupe: error: Use --resume-output (or delete the lock) to continue a previous run.",
            file=sys.stderr,
        )
        return 3

    # APPLY command
    if args.command == "apply":
        logger.info("Starting APPLY mode: %s", args.apply_report)
        logger.info("Dry run: %s, Force: %s", args.dry_run, args.force)

        banner = _banner_text(
            False,
            dry=args.dry_run,
            mode="apply",
            threads=1,   # apply is single-threaded
            gpu=False,
            backup=args.backup,
        )
        reporter = ProgressReporter(enable_dash=False, refresh_rate=0.25, banner=banner, stacked_ui=None)
        active_reporter = reporter
        reporter.start()
        try:
            report_path = Path(args.apply_report).expanduser().resolve()

            base_root: Optional[Path] = None
            if args.directories:
                try:
                    base_root = Path(
                        os.path.commonpath(
                            [str(Path(d).expanduser().resolve().absolute()) for d in args.directories]
                        )
                    )
                    logger.info("Base root for backup: %s", base_root)
                except Exception as e:
                    logger.warning("Could not compute base root: %s", e)

            backup = Path(args.backup).expanduser().resolve() if args.backup else None
            folder_priority = Path(args.folder_priority).expanduser().resolve() if args.folder_priority else None

            if getattr(args, "force_review_required", False):
                print(
                    "WARNING: -F/--force-review-required is deprecated and has no effect. "
                    "REVIEW groups (actionable=True) are applied automatically.",
                    file=sys.stderr,
                )

            count, size = apply_report(
                report_path,
                dry_run=args.dry_run,
                force=args.force,
                backup=backup,
                base_root=base_root,
                vault=None,
                folder_priority=folder_priority,
                reporter=reporter,
                verbosity=int(args.verbosity),
                full_file_names=False,
            )

            reporter.set_results(dup_groups=0, losers_count=count, bytes_total=size)
            result_msg = f"Report applied: removed/moved={count}; size={size/1_048_576:.2f} MiB"
            logger.info(result_msg)
            print(result_msg)
            if quit_requested:
                print("Apply interrupted early; some operations may have been skipped.")
            return 130 if quit_requested else 0
        except Exception as e:
            logger.error("Error applying report: %s", e)
            raise
        finally:
            reporter.stop()
            _release_output_lock(lock_file, logger)
            logger.info("Apply command completed")

    # SCAN command
    assert args.command == "scan"

    if not args.directories:
        logger.error("No directories specified for scanning")
        print(
            "video-dedupe scan: error: at least one -D/--directory is required",
            file=sys.stderr,
        )
        _release_output_lock(lock_file, logger)
        return 2

    logger.info("Starting SCAN mode for directories: %s", args.directories)

    # Build (pattern, depth) per root, expand globs
    default_depth: Optional[int] = None if args.recursive else 0
    parsed_specs: List[Tuple[Path, Optional[int]]] = []
    for spec in args.directories:
        pat, depth = _parse_dir_spec(spec, default_depth)
        for match in _expand_glob(pat):
            resolved_path = match.expanduser().resolve()
            parsed_specs.append((resolved_path, depth))

    for r, _d in parsed_specs:
        if not r.exists():
            logger.error("Directory not found: %s", r)
            print(f"video-dedupe: error: directory not found: {r}", file=sys.stderr)
            _release_output_lock(lock_file, logger)
            return 2

    patterns = _normalize_patterns(args.pattern)
    exclude_patterns = _normalize_patterns(args.exclude_pattern)
    logger.info("File patterns: %s", patterns or "all files")

    pipeline_str = _quality_to_pipeline(args.quality)
    logger.info("Pipeline stages: %s", pipeline_str)

    base_name = f"vdedup-q{args.quality}"
    cache_path = output_dir / f"{base_name}-cache.jsonl"
    report_path = output_dir / f"{base_name}-report.json"

    quality_level = _infer_quality_level(args.quality)
    subset_detect_enabled = 4 in parse_pipeline(pipeline_str) and quality_level >= 5

    sample_ratio = None
    if args.sample_percent is not None:
        sample_ratio = float(args.sample_percent) / 100.0

    cfg = PipelineConfig(
        threads=max(1, int(args.threads)),
        duration_tolerance=args.duration_tolerance,
        same_res=False,
        same_codec=False,
        same_container=False,
        phash_frames=args.phash_frames,
        phash_threshold=args.phash_threshold,
        subset_detect=subset_detect_enabled,
        subset_min_ratio=args.subset_min_ratio,
        subset_frame_threshold=max(args.phash_threshold, 12),
        gpu=False,          # resolved from gpu_mode by run_pipeline capability detection
        gpu_mode=args.gpu,
        gpu_device_id=getattr(args, "gpu_device_id", 0),
        include_partials=bool(args.include_partials),
        sample_ratio=sample_ratio,
        sample_seed=args.sample_seed,
        max_duplicates=args.max_duplicates,
    )

    banner = _banner_text(
        True,
        dry=args.dry_run,
        mode=f"Q{args.quality}",
        threads=cfg.threads,
        gpu=cfg.gpu,
        backup=None,
    )

    reporter = ProgressReporter(enable_dash=args.live, refresh_rate=0.25, banner=banner, stacked_ui=None)
    active_reporter = reporter
    try:
        reporter.start()
    except Exception as e:
        logger.error("reporter.start() crashed: %s", e, exc_info=True)
        raise

    try:
        cache = HashCache(cache_path)
        cache.open_append()
    except Exception as e:
        logger.error("HashCache creation failed: %s", e, exc_info=True)
        raise

    # Build exclusion set from reports, if any
    skip_paths: Set[Path] = set()
    if args.exclude_by_report:
        ex_paths = [Path(p).expanduser().resolve() for p in args.exclude_by_report]
        skip_paths = collect_exclusions(ex_paths)
        if skip_paths:
            logger.info("Excluding %d files from previous reports", len(skip_paths))
            print(f"Excluding {len(skip_paths)} files listed as losers in supplied report(s).")

    # Report-seeded include_paths (optional)
    include_paths: Optional[Set[Path]] = None
    if args.seed_report:
        include_paths = _build_seed_include_paths(
            seed_report=Path(args.seed_report).expanduser().resolve(),
            parsed_specs=parsed_specs,
            patterns=patterns,
            exclude_patterns=exclude_patterns,
            seed_random_per_group=args.seed_random_per_group or 0,
            sample_seed=args.sample_seed,
            skip_paths=skip_paths,
            logger=logger,
        )
        if include_paths is not None:
            logger.info("Report-seeded scan: %d total paths in include set", len(include_paths))

    try:
        stages = parse_pipeline(pipeline_str)

        # Partition roots into unlimited-depth and finite-depth batches
        unlimited_roots: List[Path] = []
        finite_expanded_roots: List[Path] = []
        for root, depth in parsed_specs:
            for d in _walk_dirs_up_to(root, depth):
                if depth is None and d == root:
                    unlimited_roots.append(d)
                else:
                    finite_expanded_roots.append(d)

        groups_all: Dict[str, Tuple[Any, List[Any]]] = {}
        group_metadata: Dict[str, Dict[str, Any]] = {}
        candidate_groups_all: Dict[str, List[Any]] = {}
        candidate_metadata_all: Dict[str, Dict[str, Any]] = {}

        def _merge_groups(dst: Dict[str, Tuple[Any, List[Any]]], src: Dict[str, Tuple[Any, List[Any]]]):
            src_meta = getattr(src, "metadata", {}) if hasattr(src, "metadata") else {}
            for k, v in src.items():
                nk = k
                i = 1
                while nk in dst and dst[nk] is not v:
                    nk = f"{k}#{i}"
                    i += 1
                dst[nk] = v
                if isinstance(src_meta, dict) and k in src_meta:
                    group_metadata[nk] = dict(src_meta[k])
            # Also merge candidate groups from this pipeline result
            src_cands = getattr(src, "candidate_groups", {})
            src_cmeta = getattr(src, "candidate_metadata", {})
            for k, v in src_cands.items():
                nk = k
                i = 1
                while nk in candidate_groups_all:
                    nk = f"{k}#{i}"
                    i += 1
                candidate_groups_all[nk] = v
                if k in src_cmeta:
                    candidate_metadata_all[nk] = dict(src_cmeta[k])

        def _merged_duplicate_count() -> int:
            return sum(max(0, len(members) - 1) for members in groups_all.values())

        def _merged_limit_reached() -> bool:
            limit = getattr(args, "max_duplicates", None)
            return limit is not None and limit > 0 and _merged_duplicate_count() >= limit

        def _run_pipeline_call(roots_list: List[Path], max_depth_val: Optional[int]):
            try:
                return run_pipeline(
                    roots=roots_list,
                    patterns=patterns,
                    exclude_patterns=exclude_patterns,
                    max_depth=max_depth_val,
                    selected_stages=stages,
                    cfg=cfg,
                    cache=cache,
                    reporter=reporter,
                    skip_paths=skip_paths,
                    include_paths=include_paths,
                )
            except TypeError as e:
                logger.warning("Multiple roots not supported, falling back to single root: %s", e)
                common: Optional[Path] = None
                try:
                    common = Path(os.path.commonpath([str(r) for r in roots_list]))
                except Exception:
                    common = None
                root = common if common and common.exists() else roots_list[0]
                if len(roots_list) > 1 and (common is None or common not in roots_list):
                    msg = "Warning: pipeline doesn't accept multiple roots; running on first directory only."
                    logger.warning(msg)
                    print(msg, file=sys.stderr)
                return run_pipeline(
                    root=root,
                    patterns=patterns,
                    exclude_patterns=exclude_patterns,
                    max_depth=max_depth_val,
                    selected_stages=stages,
                    cfg=cfg,
                    cache=cache,
                    reporter=reporter,
                    skip_paths=skip_paths,
                    include_paths=include_paths,
                )

        if unlimited_roots:
            logger.info("Running unlimited depth pipeline on %d roots", len(unlimited_roots))
            g_unlim = _run_pipeline_call(unlimited_roots, None)
            _merge_groups(groups_all, g_unlim)

        if finite_expanded_roots and not _merged_limit_reached():
            logger.info("Running finite depth pipeline on %d roots", len(finite_expanded_roots))
            g_fin = _run_pipeline_call(finite_expanded_roots, 0)
            _merge_groups(groups_all, g_fin)
        elif finite_expanded_roots:
            logger.info("Skipping finite depth pipeline because --max-duplicates limit was reached")

        logger.info("Total groups found: %d", len(groups_all))
        reporter.set_status("Selecting winners from duplicate groups")
        keep_order = ["longer", "resolution", "video-bitrate", "newer", "smaller", "deeper"]
        winners = choose_winners(groups_all, keep_order)

        logger.info("Writing report with %d groups to: %s", len(winners), report_path)
        reporter.set_status("Writing report to disk")
        review_count = sum(1 for m in group_metadata.values() if m.get("review_required") and m.get("actionable") is not False)
        report_warnings: List[str] = []
        if candidate_groups_all:
            report_warnings.append(
                f"{len(candidate_groups_all)} candidate group(s) (Q1 size / Q3 metadata) are not apply-safe. "
                "Re-run with -q 2 or -q 4+ to get content-verified results."
            )
        if review_count:
            report_warnings.append(
                f"{review_count} group(s) require review (-F to apply). "
                "Re-run with -q 7 for stronger verification."
            )
        write_report(
            report_path,
            winners,
            metadata=group_metadata,
            candidate_groups=candidate_groups_all,
            candidate_metadata=candidate_metadata_all,
            warnings=report_warnings,
        )
        print(f"Wrote report to: {report_path}")
        if quit_requested:
            print("Scan interrupted early; partial findings saved to the report above.")

        losers = [loser for (_keep, losers) in winners.values() for loser in losers]
        bytes_total = sum(int(getattr(loser, "size", 0)) for loser in losers)
        reporter.set_results(dup_groups=len(winners), losers_count=len(losers), bytes_total=bytes_total)
        reporter.set_status("Scan complete")

        if quit_requested:
            logger.warning("Scan ended early due to interrupt.")
        else:
            logger.info("Scan mode completed successfully")
        return 130 if quit_requested else 0
    except Exception as e:
        logger.error("Pipeline execution failed: %s", e)
        raise
    finally:
        if cache:
            cache.close()
        reporter.stop()
        _release_output_lock(lock_file, logger)
        logger.info("vdedup session ended")


if __name__ == "__main__":
    sys.exit(main())
