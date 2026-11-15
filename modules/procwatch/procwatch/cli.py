"""Command-line interface for ProcWatch (Phase 1: `watch` and `guard`)."""

from __future__ import annotations

import argparse
from pathlib import Path
import queue
import sys
import time
from typing import Sequence

from procwatch import __version__
from procwatch.collectors.win_event import WinEventCollector
from procwatch.collectors.wmi_trace import WmiProcessEvent, WmiProcessTraceCollector
from procwatch.config import (
    DEFAULT_AUTOMATION_TITLE_PATTERN,
    ConfigValidationError,
    GuardConfig,
    GuardMode,
    WatchConfig,
    compile_optional_regex,
)
from procwatch.correlator.ancestry import ProcessTableCache
from procwatch.correlator.engine import LiveCorrelator
from procwatch.guard.window_guard import RawWindowEvent
from procwatch.models import CollectorStats
from procwatch.mutex import CollectorAlreadyRunningError, CollectorMutex
from procwatch.renderers.console import ConsoleRenderer


def build_parser() -> argparse.ArgumentParser:
    """Build the Phase 1 CLI argument parser."""
    epilog = (
        "Distinctions:\n"
        "  Window Owner       Process owning the HWND (often WindowsTerminal.exe).\n"
        "  Suspected Cause    Candidate initiating process correlated by timing/ancestry.\n\n"
        "Planned future commands (Phases 2-4, not yet installed):\n"
        "  history, explain, mark, doctor, scan, audit, analyze, exec\n"
    )
    parser = argparse.ArgumentParser(
        prog="procwatch",
        description="Windows 11 live console/terminal popup guard and process catcher.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # 1. `procwatch watch`
    watch_p = subparsers.add_parser(
        "watch",
        help="Live stream of process and window events (read-only unless -g is set).",
        description="Observe transient console/terminal windows and process starts/stops in real time.",
    )
    watch_p.add_argument(
        "-p",
        "--popups-only",
        action="store_true",
        help="Display only events that created a window or matched popup heuristics.",
    )
    watch_p.add_argument(
        "-g",
        "--guard-windows",
        action="store_true",
        help="Enable active NeutralizeEngine window suppression while watching.",
    )
    watch_p.add_argument(
        "-m",
        "--guard-mode",
        choices=[GuardMode.OBSERVE.value, GuardMode.SMART.value, GuardMode.ALL_CONSOLES.value],
        default=GuardMode.OBSERVE.value,
        help="Guard policy when -g is active (default: observe).",
    )
    watch_p.add_argument(
        "-c",
        "--collapse-bursts",
        action="store_true",
        help="Collapse repetitive process bursts into rolling counters.",
    )
    watch_p.add_argument(
        "-s",
        "--show-headless",
        action="store_true",
        help="Include headless conhost.exe 0x4 spawns in output.",
    )
    watch_p.add_argument(
        "-f",
        "--filter-regex",
        type=str,
        default=None,
        help="Filter output by window title/class, command line, or ancestor name.",
    )
    watch_p.add_argument(
        "-o",
        "--output-file",
        type=Path,
        default=None,
        help="Append redacted JSONL events to disk.",
    )

    # 2. `procwatch guard`
    guard_p = subparsers.add_parser(
        "guard",
        help="Dedicated low-overhead window guard loop (defaults to observe mode).",
        description="Intercept newly created console/terminal popup windows without interfering with interactive terminals.",
    )
    guard_p.add_argument(
        "-m",
        "--mode",
        choices=[
            GuardMode.OBSERVE.value,
            GuardMode.SMART.value,
            GuardMode.ALL_CONSOLES.value,
            GuardMode.ALL_WINDOWS.value,
        ],
        default=GuardMode.OBSERVE.value,
        help="Suppression policy (default: observe; all-windows is experimental/unsafe).",
    )
    guard_p.add_argument(
        "-n",
        "--no-focus-restore",
        action="store_true",
        help="Minimize intercepted windows without restoring foreground focus.",
    )
    guard_p.add_argument(
        "-t",
        "--title-pattern",
        type=str,
        default=DEFAULT_AUTOMATION_TITLE_PATTERN,
        help="Regex of window titles to suppress in smart mode.",
    )
    guard_p.add_argument(
        "-e",
        "--exclude-pattern",
        type=str,
        default=None,
        help="Regex of window titles to never suppress.",
    )
    guard_p.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress console log output (for background pythonw.exe usage).",
    )
    guard_p.add_argument(
        "-o",
        "--output-file",
        type=Path,
        default=None,
        help="Append redacted JSONL window events to disk.",
    )

    return parser


def _run_live_session(
    *,
    command: str,
    guard_config: GuardConfig,
    watch_config: WatchConfig,
    renderer: ConsoleRenderer,
) -> int:
    """Run the single-owner live WinEvent + WMI + Correlator loop until Ctrl+C."""
    if sys.platform != "win32":
        print("Error: procwatch live window/process collection requires Windows (win32).", file=sys.stderr)
        return 2

    mutex = CollectorMutex(mode=guard_config.mode.value, command=command)
    try:
        mutex.acquire()
    except CollectorAlreadyRunningError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3

    stats = CollectorStats()
    win_queue: queue.Queue[RawWindowEvent] = queue.Queue(maxsize=watch_config.event_queue_maxsize)
    wmi_queue: queue.Queue[WmiProcessEvent] = queue.Queue(maxsize=watch_config.event_queue_maxsize)

    cache = ProcessTableCache(
        max_entries=watch_config.process_cache_max_entries,
        ttl_seconds=watch_config.process_cache_ttl_seconds,
    )
    seeded = cache.seed_from_snapshot()

    win_collector = WinEventCollector(guard_config=guard_config, event_queue=win_queue, stats=stats)
    wmi_collector = WmiProcessTraceCollector(event_queue=wmi_queue, stats=stats)
    wmi_status = wmi_collector.start()

    correlator = LiveCorrelator(
        process_cache=cache,
        win_queue=win_queue,
        wmi_queue=wmi_queue,
        watch_config=watch_config,
        stats=stats,
        on_incident=renderer.render,
        wmi_missing_reason=wmi_collector.missing_reason,
    )

    if not guard_config.quiet:
        print(
            f"ProcWatch {command} active (mode={guard_config.mode.value}, "
            f"seeded_procs={seeded}, wmi_trace={wmi_status}). Press Ctrl+C to stop.",
            flush=True,
        )
        if wmi_collector.last_error:
            print(f"Note: {wmi_collector.last_error}", flush=True)

    try:
        win_collector.start()
        correlator.start()
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        if not guard_config.quiet:
            print("\nStopping ProcWatch...", flush=True)
    finally:
        correlator.stop()
        win_collector.stop()
        wmi_collector.stop()
        renderer.close()
        mutex.release()

    if not guard_config.quiet:
        print(
            f"Stopped. win_events={stats.win_events_received} (dropped={stats.win_events_dropped}), "
            f"suppressed={stats.guard_suppressed_count}, allowed={stats.guard_allowed_count}, "
            f"pending={stats.guard_pending_count}, wmi_starts={stats.wmi_starts_received}.",
            flush=True,
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for `procwatch`."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    try:
        if args.command == "watch":
            effective_mode = GuardMode(args.guard_mode) if args.guard_windows else GuardMode.OBSERVE
            guard_cfg = GuardConfig(mode=effective_mode)
            watch_cfg = WatchConfig(
                popups_only=args.popups_only,
                guard_windows=args.guard_windows,
                guard_mode=effective_mode,
                collapse_bursts=args.collapse_bursts,
                show_headless=args.show_headless,
                filter_regex=compile_optional_regex(args.filter_regex),
                output_file=args.output_file,
            )
            renderer = ConsoleRenderer(
                popups_only=watch_cfg.popups_only,
                collapse_bursts=watch_cfg.collapse_bursts,
                show_headless=watch_cfg.show_headless,
                filter_regex=watch_cfg.filter_regex,
                output_file=watch_cfg.output_file,
            )
            return _run_live_session(
                command="watch",
                guard_config=guard_cfg,
                watch_config=watch_cfg,
                renderer=renderer,
            )

        if args.command == "guard":
            mode = GuardMode(args.mode)
            title_re = compile_optional_regex(args.title_pattern)
            if title_re is None:
                raise ConfigValidationError("--title-pattern cannot be empty.")
            guard_cfg = GuardConfig(
                mode=mode,
                restore_focus=not args.no_focus_restore,
                title_pattern=title_re,
                exclude_pattern=compile_optional_regex(args.exclude_pattern),
                allow_all_windows_experimental=(mode == GuardMode.ALL_WINDOWS),
                quiet=args.quiet,
            )
            watch_cfg = WatchConfig(
                popups_only=True,
                guard_windows=(mode != GuardMode.OBSERVE),
                guard_mode=mode,
                output_file=args.output_file,
            )
            renderer = ConsoleRenderer(
                popups_only=True,
                output_file=watch_cfg.output_file,
                quiet=guard_cfg.quiet,
            )
            return _run_live_session(
                command="guard",
                guard_config=guard_cfg,
                watch_config=watch_cfg,
                renderer=renderer,
            )
    except ConfigValidationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    parser.print_help()
    return 1
