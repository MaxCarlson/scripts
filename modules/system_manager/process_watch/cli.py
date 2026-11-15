"""Unified CLI and legacy compatibility adapter for proc-stats and sm proc watch."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from .exporter import render_csv, render_json, render_rich_table, write_export_file
from .filters import COLUMN_PRESETS, SORT_FIELDS, ProcessFilter, filter_processes, sort_processes
from .sampler import ProcessSampler, sample_once

LEGACY_SORT_MAP = {
    "cpu": "cpu",
    "memory": "rss",
    "disk": "io_total",
    "alphabetical": "name",
    "random": "random",
}


def add_watch_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Register modern proc-stats arguments on a parser or subparser."""
    parser.add_argument("-g", "--glob", action="append", default=[], help="Include glob pattern (repeatable, OR semantics)")
    parser.add_argument("-e", "--exclude-glob", action="append", default=[], help="Exclude glob pattern (repeatable)")
    parser.add_argument("-p", "--pid", action="append", type=int, default=[], help="Filter to PID (repeatable)")
    parser.add_argument("-n", "--rows", type=int, default=None, help="Initial visible row count")
    parser.add_argument("-i", "--interval", type=float, default=1.0, help="Sampling interval in seconds (default: 1.0)")
    parser.add_argument("-s", "--sort", choices=SORT_FIELDS, default="cpu", help="Initial sort field (default: cpu)")
    parser.add_argument("-r", "--reverse", action="store_true", help="Reverse default sort direction")
    parser.add_argument("-R", "--recursive", action="store_true", help="Include descendants of selected PIDs")
    parser.add_argument("-G", "--gpu", action="store_true", help="Enable supported GPU telemetry")
    parser.add_argument(
        "--gpu-interval",
        type=float,
        default=4.0,
        help="GPU polling cache interval in seconds (default: 4.0)",
    )
    parser.add_argument(
        "-C",
        "--columns",
        choices=sorted(COLUMN_PRESETS.keys()),
        default="default",
        help="Initial column preset (default: default)",
    )
    parser.add_argument(
        "-m",
        "--match-command-line",
        action="store_true",
        help="Opt into matching globs/search against command-line arguments",
    )
    parser.add_argument("-a", "--aggregate", action="store_true", help="Enable subtree aggregation")
    parser.add_argument("-1", "--once", action="store_true", help="Sample once and exit")
    parser.add_argument(
        "-f",
        "--format",
        choices=("table", "json", "csv"),
        default="table",
        help="One-shot output format (default: table)",
    )
    parser.add_argument("-o", "--output", type=Path, default=None, help="Write one-shot output to file path")
    parser.add_argument("-F", "--force", action="store_true", help="Overwrite existing file when using -o/--output")
    return parser


def build_parser(prog: str = "proc-stats") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Interactive read-only process explorer and one-shot resource reporter.",
    )
    add_watch_arguments(parser)
    return parser


def _validate_args(args: argparse.Namespace) -> Optional[str]:
    if args.interval is not None and args.interval <= 0:
        return "Interval (--interval) must be greater than 0."
    if getattr(args, "gpu_interval", 4.0) <= 0:
        return "GPU interval (--gpu-interval) must be greater than 0."
    if args.rows is not None and args.rows <= 0:
        return "Row count (--rows) must be a positive integer."
    return None


def run_from_args(args: argparse.Namespace) -> int:
    """Execute one-shot export/report or launch the interactive Textual TUI."""
    err = _validate_args(args)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return 2

    flt = ProcessFilter(
        include_globs=list(args.glob or []),
        exclude_globs=list(args.exclude_glob or []),
        pids=list(args.pid or []),
        recursive=bool(args.recursive),
        match_cmdline=bool(args.match_command_line),
    )

    default_desc = args.sort not in ("name", "pid")
    descending = (not default_desc) if getattr(args, "reverse", False) else default_desc

    sampler = ProcessSampler(
        enable_gpu=bool(args.gpu),
        gpu_ttl_seconds=float(getattr(args, "gpu_interval", 4.0)),
    )

    one_shot = bool(args.once or args.output is not None or args.format != "table" or not sys.stdout.isatty())
    if one_shot:
        snapshot = sample_once(sampler, interval_seconds=float(args.interval))
        filtered = filter_processes(snapshot.processes, flt, snapshot.children_map)
        ordered = sort_processes(
            filtered,
            sort_key=args.sort,
            descending=descending,
            aggregated=bool(args.aggregate),
        )
        if args.rows is not None and args.rows > 0:
            ordered = ordered[: args.rows]

        if args.format == "json":
            output_text = render_json(snapshot, ordered, aggregated=bool(args.aggregate))
        elif args.format == "csv":
            output_text = render_csv(ordered, aggregated=bool(args.aggregate))
        else:
            cols = COLUMN_PRESETS.get(args.columns, COLUMN_PRESETS["default"])
            output_text = render_rich_table(
                snapshot,
                ordered,
                columns=cols,
                aggregated=bool(args.aggregate),
                limit=args.rows,
            )

        if args.output is not None:
            try:
                write_export_file(args.output, output_text, force=bool(args.force))
            except FileExistsError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 2
            except OSError as exc:
                print(f"Error writing {args.output}: {exc}", file=sys.stderr)
                return 1
        else:
            print(output_text, end="" if output_text.endswith("\n") else "\n")
        return 0

    try:
        from .tui import ProcessWatchApp
    except ImportError as exc:
        print(
            "Error: Interactive TUI requires the optional 'textual' package (Python >= 3.9). "
            "Install with `pip install system_manager[tui]` or pass `-1/--once` for noninteractive output.\n"
            f"Details: {exc}",
            file=sys.stderr,
        )
        return 2

    app = ProcessWatchApp(
        sampler,
        initial_filter=flt,
        interval_seconds=float(args.interval),
        sort_key=args.sort,
        sort_descending=descending,
        visible_rows=args.rows,
        column_preset=args.columns,
        aggregated=bool(args.aggregate),
    )
    app.run()
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser("proc-stats")
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run_from_args(args)


def translate_legacy_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse legacy proc_stats.py flags (preserving ms units and bare-glob substring match)."""
    parser = argparse.ArgumentParser(
        prog="proc_stats",
        description="Live process stats (legacy-compatible options).",
    )
    parser.add_argument("-n", "--number-of-procs", type=int, default=3, help="Number of processes to display")
    parser.add_argument("-g", "--glob", type=str, default=None, help="Glob pattern to match process names (default: all)")
    parser.add_argument(
        "-s",
        "--sort-ordering",
        choices=list(LEGACY_SORT_MAP.keys()),
        default="alphabetical",
        help="Sort by: cpu, memory, disk, alphabetical, or random",
    )
    parser.add_argument("-a", "--analysis-time", type=int, default=1000, help="Milliseconds to sample CPU & I/O")
    parser.add_argument("-u", "--update-frequency", type=int, default=1000, help="Milliseconds between screen refreshes")
    parser.add_argument("-1", "--once", action="store_true", help="Sample once and exit")

    legacy = parser.parse_args(list(argv) if argv is not None else None)
    if legacy.analysis_time <= 0:
        parser.error("--analysis-time must be > 0 ms")
    if legacy.update_frequency <= 0:
        parser.error("--update-frequency must be > 0 ms")

    globs: List[str] = []
    if legacy.glob is not None:
        if not any(ch in legacy.glob for ch in "*?[]"):
            globs = [f"*{legacy.glob}*"]
        else:
            globs = [legacy.glob]

    # Legacy proc_stats.py slept for analysis_time during sampling and update_frequency between frames.
    # In one-shot mode, analysis_time is the exact sampling window; in live mode, use the larger period.
    interval_sec = (
        legacy.analysis_time / 1000.0
        if legacy.once
        else max(legacy.analysis_time, legacy.update_frequency) / 1000.0
    )
    sort_key = LEGACY_SORT_MAP[legacy.sort_ordering]

    return argparse.Namespace(
        glob=globs,
        exclude_glob=[],
        pid=[],
        rows=legacy.number_of_procs,
        interval=interval_sec,
        sort=sort_key,
        reverse=False,
        recursive=False,
        gpu=False,
        gpu_interval=4.0,
        columns="default",
        match_command_line=False,
        aggregate=False,
        once=legacy.once,
        format="table",
        output=None,
        force=False,
    )


def main_legacy(argv: Optional[Sequence[str]] = None) -> int:
    args = translate_legacy_args(argv)
    return run_from_args(args)
