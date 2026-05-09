"""
ytaedl — top-level CLI dispatcher.

Usage
-----
  ytaedl run      [options]          Interactive download manager
  ytaedl worker   [options]          Single URL-file downloader
  ytaedl cleanup  partial|index ...  Maintenance (clean partial dirs / rebuild index)
  ytaedl urls     [options]          URL file scanning and stats
  ytaedl archive  [options]          Archive file management

Run ``ytaedl <subcommand> --help`` for the full option list of each subcommand.
"""

from __future__ import annotations

import sys
import textwrap
from typing import Optional, Sequence

# Short descriptions shown in top-level --help
_SUBCOMMAND_HELP = {
    "run": "Interactive download manager (all runtime options)",
    "worker": "Single URL-file downloader",
    "cleanup": "Maintenance: delete partial dirs or rebuild the domain index",
    "urls": "URL file scanning, statistics, and ranking",
    "archive": "Archive file management (rebuild, inspect, repair)",
}

_EXAMPLES = textwrap.dedent("""\
    Examples
    --------
      ytaedl run -t 8 -P B:\\stars\\ -s ./files/downloads/stars
      ytaedl worker -f stars/upperfloor2.txt -P B:\\stars\\
      ytaedl cleanup partial -P B:\\stars\\ --dry-run
      ytaedl cleanup partial -P B:\\stars\\
      ytaedl cleanup index --stars-dir ./files/downloads/stars
      ytaedl urls --help
      ytaedl archive --help
""")


def _print_top_help(prog: str = "ytaedl") -> None:
    lines = [
        f"usage: {prog} <subcommand> [options]",
        "",
        "Subcommands:",
    ]
    width = max(len(k) for k in _SUBCOMMAND_HELP) + 2
    for name, desc in _SUBCOMMAND_HELP.items():
        lines.append(f"  {name:<{width}}{desc}")
    lines += ["", _EXAMPLES.rstrip(), ""]
    lines.append(f"Run '{prog} <subcommand> --help' for subcommand-specific options.")
    print("\n".join(lines))


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for the ``ytaedl`` console script."""
    argv_list = list(argv) if argv is not None else sys.argv[1:]

    if not argv_list or argv_list[0] in ("-h", "--help"):
        _print_top_help()
        return 0

    subcommand = argv_list[0]
    rest = argv_list[1:]

    if subcommand == "run":
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

    # Unknown subcommand
    print(f"ytaedl: unknown subcommand '{subcommand}'", file=sys.stderr)
    print("Run 'ytaedl --help' to list available subcommands.", file=sys.stderr)
    return 2
