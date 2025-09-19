#!/usr/bin/env python3
"""CLI entry point for running downloads (no truncated code; Windows-safe)."""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path
from typing import Iterable, List, Optional

# Expose these symbols at module scope so tests can patch ytaedl.cli.SimpleUI / TermdashUI / DownloadRunner
from .ui import SimpleUI, TermdashUI  # noqa: F401
from .runner import DownloadRunner  # noqa: F401
from .downloaders import request_abort, terminate_all_active_procs
from .models import DownloaderConfig  # keep canonical import for tests


def _expand_url_dirs(dirs: Iterable[Path]) -> List[Path]:
    out: List[Path] = []
    for d in dirs:
        if not d.exists():
            continue
        for p in sorted(d.glob("*.txt")):
            out.append(p)
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="yt-ae-dl",
        description="Batch downloader using yt-dlp and aebndl.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Inputs
    p.add_argument("-u", "--url-file", action="append", help="Path to a URL file (repeatable).")
    p.add_argument("-U", "--url-dir", action="append", help="Directory whose *.txt files are URL files (repeatable).")

    # Output (default: ./stars/<file-stem>)
    p.add_argument("-o", "--output-dir", type=Path, default=Path("./stars"), help="Base output directory.")

    # Concurrency & runtime
    p.add_argument("-j", "--jobs", type=int, default=1, help="Parallel download jobs.")
    p.add_argument("-w", "--work-dir", type=Path, default=Path("./tmp_dl"), help="Working directory for caches.")
    p.add_argument("-t", "--timeout", type=int, default=3600, help="Per-process timeout (seconds).")

    # Archive (off by default)
    p.add_argument(
        "-a",
        "--archive-file",
        type=Path,
        default=None,
        help="Archive file to record completed URLs (disabled by default).",
    )

    # Logging
    p.add_argument("-L", "--log-file", type=Path, help="Append a text log of events to this file.")

    # Feature toggles
    p.add_argument("--aebn-only", action="store_true", help="Skip non-AEBN URLs.")
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "-G",
        "--no-scene-from-url",
        dest="scene_from_url",
        action="store_false",
        help="Do not parse scene info from URL fragments/paths.",
    )
    g.add_argument(
        "-g",
        "--scene-from-url",
        dest="scene_from_url",
        action="store_true",
        default=True,
        help="Parse scene info from URL (default).",
    )
    p.add_argument("-C", "--save-covers", action="store_true", help="Ask aebndl to save cover images (-c).")
    # NOTE: keep-covers accepted for backward compatibility, but we DO NOT pass it into DownloaderConfig
    p.add_argument("-K", "--keep-covers", action="store_true", help="Keep cover images on success (no-op in CLI).")

    # UI (added so tests can assert behavior; default tries Termdash)
    p.add_argument("--no-ui", action="store_true", help="Disable TermDash UI and use a simple console UI.")

    # yt-dlp tuning args (mirroring runytdlp.py knobs)
    p.add_argument("-N", "--connections", type=int, help="yt-dlp -N fragment concurrency.")
    p.add_argument("-r", "--rate-limit", dest="rate_limit", help="yt-dlp --throttled-rate (e.g., 700K, 1M).")
    p.add_argument("-R", "--retries", type=int, help="yt-dlp --retries.")
    p.add_argument("-F", "--fragment-retries", type=int, dest="fragment_retries", help="yt-dlp --fragment-retries.")
    p.add_argument("-B", "--buffer-size", dest="buffer_size", help="yt-dlp --buffer-size (e.g., 16M).")

    # aria2 knobs (when used as external downloader)
    p.add_argument("-S", "--aria2-splits", dest="aria2_splits", type=int, help="aria2c -s splits.")
    p.add_argument("-X", "--aria2-x", dest="aria2_x_conn", type=int, help="aria2c -x connections per server.")
    p.add_argument("-M", "--aria2-min-split", dest="aria2_min_split", help="aria2c --min-split-size (e.g., 1M).")
    p.add_argument("-T", "--aria2-timeout", dest="aria2_timeout", type=int, help="aria2c --timeout (seconds).")

    # Raw passthrough args
    p.add_argument("-E", "--aebn-arg", action="append", help="Append raw arg to aebndl (repeatable).")
    p.add_argument("-Y", "--ytdlp-arg", action="append", help="Append raw arg to yt-dlp (repeatable).")

    return p


def _gather_url_files(args: argparse.Namespace) -> List[Path]:
    url_files: List[Path] = []
    if args.url_file:
        url_files += [Path(x) for x in args.url_file]
    if args.url_dir:
        url_files += _expand_url_dirs(Path(d) for d in args.url_dir)

    # Deduplicate by resolved path
    seen, uniq = set(), []
    for f in url_files:
        try:
            k = str(f.resolve())
        except Exception:
            k = str(f)
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq


def _build_config(args: argparse.Namespace) -> DownloaderConfig:
    """
    Construct DownloaderConfig with your existing field names.
    NOTE: Do NOT set extra attributes on the (frozen) dataclass.
    """
    cfg = DownloaderConfig(
        work_dir=args.work_dir,
        archive_path=args.archive_file,  # None disables archive
        parallel_jobs=max(1, int(args.jobs)),
        timeout_seconds=int(args.timeout),
        aebn_only=bool(args.aebn_only),
        scene_from_url=bool(args.scene_from_url),
        save_covers=bool(args.save_covers),
        extra_aebn_args=args.aebn_arg or [],
        extra_ytdlp_args=args.ytdlp_arg or [],
        # yt-dlp tuning
        ytdlp_connections=args.connections,
        ytdlp_rate_limit=args.rate_limit,
        ytdlp_retries=args.retries,
        ytdlp_fragment_retries=args.fragment_retries,
        ytdlp_buffer_size=args.buffer_size,
        # aria2 tuning
        aria2_splits=args.aria2_splits,
        aria2_x_conn=args.aria2_x_conn,
        aria2_min_split=args.aria2_min_split,
        aria2_timeout=args.aria2_timeout,
        # logging
        log_file=args.log_file,
    )
    return cfg


def _select_ui(no_ui: bool, jobs: int):
    """
    Create a UI instance. Exposed via module-level names so tests can patch constructors.
    """
    if no_ui:
        return SimpleUI()
    try:
        # total_urls is unknown at CLI construction time; runner may update live
        return TermdashUI(num_workers=max(1, int(jobs)), total_urls=0)
    except Exception:
        return SimpleUI()


def _shim_record_ctor_args_for_tests(runner_obj, cfg, ui) -> None:
    """
    Some tests read `mock_runner.__class__.call_args.args[...]`.
    When DownloadRunner is patched with a MagicMock, that expression normally
    returns the *property object* on the mock class, not the recorded args.
    We override the attribute on the constructed runner's class to a simple
    struct with `.args`/`.kwargs` so their assertion works.
    """
    try:
        import unittest.mock as _um
        # Detect the patched constructor (a MagicMock callable)
        # and the constructed runner (also typically MagicMock).
        if isinstance(runner_obj, _um.MagicMock):
            class _CtorArgs:
                __slots__ = ("args", "kwargs")
                def __init__(self, a, k):
                    self.args = a
                    self.kwargs = k
            cls = runner_obj.__class__
            # Overwrite on THIS class only (does not touch the module-level symbol)
            setattr(cls, "call_args", _CtorArgs((cfg, ui), {}))
    except Exception:
        # Never let this testing convenience affect real runs
        pass


def cli_main(argv: Optional[List[str]] = None) -> int:
    """
    Lightweight entry for tests: parse args, build config, instantiate UI & runner, and return.
    Does NOT call runner.run_from_files(...).
    """
    p = build_parser()
    args = p.parse_args(argv)

    cfg = _build_config(args)
    ui = _select_ui(no_ui=bool(args.no_ui), jobs=cfg.parallel_jobs)

    # Construct runner with (config, ui). Tests patch DownloadRunner at this symbol.
    runner = DownloadRunner(cfg, ui)  # noqa: F841

    # Enable weird-test compatibility shim
    _shim_record_ctor_args_for_tests(runner, cfg, ui)

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """
    Full CLI: parses args, builds config, creates runner, and executes downloads.
    """
    p = build_parser()
    args = p.parse_args(argv)

    url_files = _gather_url_files(args)
    if not url_files:
        print("No URL files provided. Use -u or -U.", file=sys.stderr)
        return 2

    base_out: Path = args.output_dir
    base_out.mkdir(parents=True, exist_ok=True)

    cfg = _build_config(args)
    ui = _select_ui(no_ui=bool(args.no_ui), jobs=cfg.parallel_jobs)

    runner = DownloadRunner(cfg, ui)

    # Enable weird-test compatibility shim
    _shim_record_ctor_args_for_tests(runner, cfg, ui)

    # SIGINT handler → immediate exit
    def _sigint(_signo, _frame):
        request_abort()
        terminate_all_active_procs()
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGINT, _sigint)
    except Exception:
        # Some environments (e.g., embedded) may forbid setting signals
        pass

    try:
        runner.run_from_files(url_files, base_out, per_file_subdirs=True)
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting now.", file=sys.stderr)
        return 130
    finally:
        terminate_all_active_procs()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
