from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Sequence

from .concurrency import DEFAULT_MAX_OUTER_WORKERS

RunMode = Literal["normal", "optimize", "benchmark"]


@dataclass(frozen=True, slots=True)
class CommandShape:
    argv: tuple[str, ...]
    run_mode: RunMode = "normal"
    advanced_config: bool = False
    archive_config: bool = False


def normalize_command_shape(argv: Sequence[str]) -> CommandShape:
    values = list(argv)
    run_mode: RunMode = "normal"
    advanced = False
    archive_config = False

    if values and values[0] == "run":
        if len(values) > 1 and values[1] in {"optimize", "benchmark", "config"}:
            token = values.pop(1)
            if token == "config":
                advanced = True
            else:
                run_mode = token  # type: ignore[assignment]
                if len(values) > 1 and values[1] == "config":
                    values.pop(1)
                    advanced = True
    elif len(values) > 1 and values[0] == "archive" and values[1] == "config":
        values.pop(1)
        archive_config = True

    return CommandShape(tuple(values), run_mode, advanced, archive_config)


def _help(value: str, visible: bool) -> str:
    return value if visible else argparse.SUPPRESS


def add_run_arguments(
    parser: argparse.ArgumentParser,
    *,
    mode: RunMode,
    advanced: bool,
    path_type: Callable[[str], Path],
) -> None:
    parser.set_defaults(
        run_mode=mode,
        advanced_config=advanced,
        run_id=None,
        auto_tune=False,
        tune_workers=None,
        tune_image_workers=None,
        tune_sample_images=24,
    )
    if not advanced and mode == "normal":
        parser.epilog = (
            "Additional modes: `mangadl run optimize --help`, "
            "`mangadl run benchmark --help`, and `mangadl run config --help`."
        )
    elif not advanced:
        parser.epilog = (
            f"Advanced settings: `mangadl run {mode} config --help`."
        )

    parser.add_argument("-i", "--input-file", action="append", type=path_type, default=[], help="UTF-8 URL file; repeatable.")
    parser.add_argument("-u", "--url", action="append", default=[], help="Direct series/gallery URL; repeatable.")
    parser.add_argument("-d", "--destination", type=path_type, required=True, help="Destination library root.")
    parser.add_argument("-a", "--archive", type=path_type, required=True, help="Download archive database.")
    parser.add_argument("-w", "--workers", type=int, default=2, help="Initial concurrent series workers (default: 2).")
    parser.add_argument(
        "-I",
        "--image-workers",
        type=int,
        default=4,
        help="Manga18FX image downloads per newly started series worker (default: 4).",
    )

    expert = advanced
    parser.add_argument(
        "-s",
        "--state-db",
        type=path_type,
        default=path_type("mangadl-state.sqlite3"),
        help=_help("Manager state database.", expert),
    )
    parser.add_argument(
        "-m",
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_OUTER_WORKERS,
        help=_help("Outer-worker safety ceiling (default: 4; hard maximum: 8).", expert or mode != "normal"),
    )
    parser.add_argument(
        "-U",
        "--worker-start-delay",
        type=float,
        default=2.0,
        help=_help("Seconds between outer-worker launches (default: 2).", expert),
    )
    parser.add_argument(
        "-b",
        "--backend",
        choices=("auto", "gallery-dl", "native-nhentai", "hdporncomics", "manga18fx"),
        default="auto",
        help=_help("Force one backend instead of automatic routing.", expert),
    )
    parser.add_argument(
        "-e",
        "--hdporncomics-executable",
        help=_help("hdporncomics executable path or name.", expert),
    )
    parser.add_argument(
        "-H",
        "--hdporncomics-threads",
        type=int,
        default=8,
        help=_help("Internal hdporncomics threads (default: 8).", expert),
    )
    parser.add_argument("-c", "--config", type=path_type, help=_help("Reserved mangadl TOML configuration path.", expert))
    parser.add_argument("-g", "--gallery-config", type=path_type, help=_help("gallery-dl configuration file.", expert))
    parser.add_argument(
        "-l",
        "--log-dir",
        type=path_type,
        default=path_type("mangadl-logs"),
        help=_help("Run log root.", expert),
    )
    parser.add_argument("-r", "--retries", type=int, default=3, help=_help("Transient retry count.", expert))
    parser.add_argument(
        "-t",
        "--retry-wait",
        type=float,
        default=5.0,
        help=_help("Initial transient retry delay in seconds.", expert),
    )
    parser.add_argument("-x", "--max-rate", help=_help("Per-worker gallery-dl rate limit, such as 2M.", expert))
    parser.add_argument("-C", "--cookies", type=path_type, help=_help("Netscape/Mozilla cookies file.", expert))
    parser.add_argument(
        "-B",
        "--cookies-browser",
        help=_help("Browser cookie source reserved for gallery-dl configuration.", expert),
    )
    parser.add_argument(
        "-k",
        "--gallery-user-agent",
        help=_help("Explicit gallery-dl User-Agent; takes precedence over managed auth.", expert),
    )
    parser.add_argument(
        "-z",
        "--auth-dir",
        type=path_type,
        help=_help("Managed per-domain gallery authentication root.", expert),
    )
    parser.add_argument(
        "-y",
        "--auth-browser",
        choices=("chrome", "edge", "firefox"),
        default="chrome",
        help=_help("Browser used for automatic gallery authentication (default: chrome).", expert),
    )
    parser.add_argument(
        "-f",
        "--no-auth-refresh",
        action="store_true",
        help=_help("Use stored profiles but do not launch a browser after an auth challenge.", expert),
    )
    parser.add_argument("-n", "--dry-run", action="store_true", help=_help("Parse and route without downloading.", expert))
    parser.add_argument("-N", "--no-ui", action="store_true", help=_help("Disable the terminal dashboard.", expert))
    parser.add_argument("-q", "--quiet", action="store_true", help=_help("Print only the final machine-readable summary.", expert))
    parser.add_argument("-v", "--verbose", action="count", default=0, help=_help("Increase diagnostics.", expert))
    parser.add_argument(
        "-A",
        "--anonymize-logs",
        action="store_true",
        help=_help("Reserve URL-anonymized log output.", expert),
    )

    if mode in {"optimize", "benchmark"}:
        parser.add_argument("-p", "--min-workers", type=int, default=1, help="Minimum outer workers to test.")
        parser.add_argument("-P", "--min-image-workers", type=int, default=1, help="Minimum image workers to test.")
        parser.add_argument("-M", "--max-image-workers", type=int, default=8, help="Maximum image workers to test.")
        parser.add_argument(
            "-E",
            "--evaluation",
            choices=("complete", "timed"),
            default="complete" if mode == "optimize" else "timed",
            help="Use complete-series trials or bounded timed trials.",
        )
        parser.add_argument(
            "-D",
            "--trial-seconds",
            type=float,
            default=30.0,
            help="Seconds per timed state (default: 30).",
        )
        parser.add_argument(
            "-Q",
            "--trials",
            type=int,
            default=12 if mode == "optimize" else 1,
            help="Adaptive trial count, or complete matrix rounds for benchmark.",
        )
        parser.add_argument(
            "-O",
            "--optimization-report",
            type=path_type,
            help="JSON state/trial report path; defaults under the log directory.",
        )
        parser.add_argument(
            "-o",
            "--report-only",
            action="store_true",
            help="Stop after optimization/benchmarking instead of starting the real run.",
        )
        parser.add_argument(
            "-Z",
            "--seed",
            type=int,
            help=_help("Deterministic adaptive-selection seed.", expert),
        )

    if mode == "normal":
        parser.add_argument("-T", "--auto-tune", action="store_true", help=argparse.SUPPRESS)
        parser.add_argument("-W", "--tune-workers", help=argparse.SUPPRESS)
        parser.add_argument("-Y", "--tune-image-workers", help=argparse.SUPPRESS)
        parser.add_argument("-D", "--tune-seconds", type=float, default=8.0, help=argparse.SUPPRESS)
        parser.add_argument("-Q", "--tune-rounds", type=int, default=2, help=argparse.SUPPRESS)
        parser.add_argument("-K", "--tune-sample-images", type=int, default=24, help=argparse.SUPPRESS)
        parser.add_argument("-O", "--tune-report", type=path_type, help=argparse.SUPPRESS)
    else:
        parser.set_defaults(
            tune_seconds=30.0,
            tune_rounds=1,
            tune_report=None,
        )
