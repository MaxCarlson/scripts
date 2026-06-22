"""
ytaedl — top-level CLI dispatcher.

Usage
-----
  ytaedl run               [options]   Interactive download manager (core flags)
  ytaedl run watcher       [options]   Run + MP4 watcher (watcher flags shown)
  ytaedl run grid          [options]   Run + yt-dlp grid search (grid flags shown)
  ytaedl run webview       [options]   Run + TUI web mirror (webview flags shown)
  ytaedl run disable       [options]   Run + disable/tuning flags (disable flags shown)
  ytaedl worker            [options]   Single URL-file downloader
  ytaedl cleanup partial|index ...     Maintenance (clean partial dirs / rebuild index)
  ytaedl urls              [options]   URL file scanning and stats
  ytaedl archive           [options]   Archive file management
  ytaedl archive validate  [options]   Validate archive/domain_index state
  ytaedl archive apply-plan -p plan.json

Run ``ytaedl <subcommand> --help`` for the full option list of each subcommand.
Run ``ytaedl run <profile> --help`` for coloured, focused help on a run profile.
"""

from __future__ import annotations

import sys
import textwrap
from typing import Optional, Sequence

from . import __version__ as YTAEDL_VERSION

# Known ``ytaedl run`` profile sub-subcommands
_RUN_PROFILES = ("watcher", "grid", "webview", "disable")

# Short descriptions shown in top-level --help
_SUBCOMMAND_HELP = {
    "run":     "Interactive download manager (+ run watcher/grid/webview/disable profiles)",
    "worker":  "Single URL-file downloader",
    "cleanup": "Maintenance: delete partial dirs or rebuild the domain index",
    "urls":    "URL file scanning, statistics, and ranking",
    "archive": "Archive file management (rebuild, validate, apply-plan)",
    "summary": "Display real-time statistics and active locks across ytaedl instances",
}

_EXAMPLES = textwrap.dedent("""\
    Examples
    --------
      ytaedl run -t 8 -P B:\\stars\\ -s ./files/downloads/stars
      ytaedl run watcher -t 8 -P B:\\stars\\ -F 75
      ytaedl run grid    -t 4 -P B:\\stars\\
      ytaedl run disable -t 8 --no-extdl-fallback
      ytaedl worker -f stars/upperfloor2.txt -P B:\\stars\\
      ytaedl cleanup partial -P B:\\stars\\ --dry-run
      ytaedl cleanup index --stars-dir ./files/downloads/stars
      ytaedl urls --help
      ytaedl archive --help
      ytaedl archive validate -a ./archive -g ./logs -L ./stars
      ytaedl archive apply-plan -p archive-fixes.json
""")


def _print_top_help(prog: str = "ytaedl") -> None:
    lines = [
        f"ytaedl {YTAEDL_VERSION}",
        "",
        f"usage: {prog} <subcommand> [options]",
        "",
        "Subcommands:",
    ]
    width = max(len(k) for k in _SUBCOMMAND_HELP) + 2
    for name, desc in _SUBCOMMAND_HELP.items():
        lines.append(f"  {name:<{width}}{desc}")
    lines += [
        "",
        "  Run profiles (focused help, auto-enable a feature):",
        "    ytaedl run watcher -h    MP4 watcher flags",
        "    ytaedl run grid    -h    yt-dlp grid-search flags",
        "    ytaedl run webview -h    TUI web-mirror flags",
        "    ytaedl run disable -h    feature-disable / tuning flags",
        "",
        _EXAMPLES.rstrip(),
        "",
        f"Run '{prog} <subcommand> --help' for subcommand-specific options.",
    ]
    print("\n".join(lines))


def _run_with_profile(profile: str, rest: list[str]) -> int:
    """
    Parse *rest* with the combined run+profile parser, inject auto-enable flags,
    and call ``run_main`` with the resulting namespace.

    This lets ``ytaedl run watcher -t 8 -F 75`` work without duplicating any
    argument definitions — the combined parser is assembled from the same helper
    functions used by the base ``make_parser()``.
    """
    from ._cli_help import make_profile_parser, profile_auto_flags
    from .manager import run_main

    parser = make_profile_parser(profile)

    # Show help immediately (--help / -h) rather than letting run_main do it,
    # so the user sees the combined coloured help for the profile.
    if not rest or rest[0] in ("-h", "--help"):
        parser.print_help()
        return 0

    ns = parser.parse_args(rest)

    # Inject the feature flag that this profile auto-enables
    for attr, value in profile_auto_flags(profile).items():
        setattr(ns, attr, value)

    return run_main(_ns=ns)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for the ``ytaedl`` console script."""
    argv_list = list(argv) if argv is not None else sys.argv[1:]

    if not argv_list or argv_list[0] in ("-h", "--help"):
        _print_top_help()
        return 0

    subcommand = argv_list[0]
    rest = argv_list[1:]

    if subcommand == "run":
        # Check for an optional profile sub-subcommand: ytaedl run watcher ...
        if rest and rest[0] in _RUN_PROFILES:
            return _run_with_profile(rest[0], rest[1:])
        from .manager import run_main
        return run_main(rest)

    if subcommand == "worker":
        from .downloader import main as worker_main
        return worker_main(rest)

    if subcommand == "cleanup":
        from .cleanup_cli import main as cleanup_main
        return cleanup_main(rest)

    if subcommand == "urls":
        from . import urlscan
        return urlscan.cli_main(rest)

    if subcommand == "archive":
        from . import archive_builder
        return archive_builder.cli_main(rest)

    if subcommand == "summary":
        from .summary import main as summary_main
        return summary_main(rest)

    # Unknown subcommand
    print(f"ytaedl: unknown subcommand '{subcommand}'", file=sys.stderr)
    print("Run 'ytaedl --help' to list available subcommands.", file=sys.stderr)
    return 2
