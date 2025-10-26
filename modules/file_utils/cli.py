#!/usr/bin/env python
"""
Main CLI entry point for the file-utils tool.
"""
from __future__ import annotations

import argparse
import sys
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A collection of file utilities.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- ls command ---
    ls_parser = subparsers.add_parser("ls", help="Interactive file and directory lister.")
    ls_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to inspect (defaults to current directory).",
    )
    ls_parser.add_argument(
        "-d",
        "--depth",
        type=int,
        default=0,
        help="Recursion depth. 0 for current directory only.",
    )
    ls_parser.add_argument(
        "-g",
        "--glob",
        metavar="PATTERN",
        help="Initial glob pattern to filter entries (e.g. '*.py').",
    )
    ls_parser.add_argument(
        "-s",
        "--sort",
        choices=("created", "modified", "accessed", "size", "name", "c", "m", "a", "s", "n"),
        default="created",
        help="Initial sort field: created/c, modified/m, accessed/a, size/s, name/n.",
    )
    ls_parser.add_argument(
        "-o",
        "--order",
        choices=("asc", "desc"),
        default="desc",
        help="Initial sort order to use.",
    )
    ls_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output in JSON format instead of launching TUI.",
    )
    ls_parser.add_argument(
        "--no-dirs-first",
        action="store_true",
        help="Don't group directories before files (default: dirs first).",
    )
    ls_parser.add_argument(
        "-S",
        "--calc-sizes",
        action="store_true",
        help="Calculate actual recursive sizes for directories.",
    )

    args = parser.parse_args(argv)

    if args.command == "ls":
        from . import lister
        return lister.run_lister(args)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
