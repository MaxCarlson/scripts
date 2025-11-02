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

    # --- replace command ---
    replace_parser = subparsers.add_parser(
        "replace",
        help="Mass find and replace using ripgrep.",
        description="Find and replace text across multiple files using ripgrep. "
                    "Supports replacing text or deleting entire lines.",
    )
    replace_parser.add_argument(
        "-p",
        "--pattern",
        required=True,
        help="Regex pattern to search for.",
    )
    replace_parser.add_argument(
        "-r",
        "--replacement",
        default=None,
        help="Replacement text. Cannot be used with --delete-line.",
    )
    replace_parser.add_argument(
        "-d",
        "--delete-line",
        action="store_true",
        help="Delete entire line containing match. Cannot be used with --replacement.",
    )
    replace_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making actual changes.",
    )
    replace_parser.add_argument(
        "-f",
        "--first-only",
        action="store_true",
        help="Only replace the first match in each file.",
    )
    replace_parser.add_argument(
        "-l",
        "--line-number",
        type=int,
        metavar="N",
        help="Only replace matches on line number N (1-indexed).",
    )
    replace_parser.add_argument(
        "-m",
        "--max-per-file",
        type=int,
        metavar="N",
        help="Maximum number of replacements per file.",
    )
    replace_parser.add_argument(
        "-i",
        "--ignore-case",
        action="store_true",
        help="Case insensitive search.",
    )
    replace_parser.add_argument(
        "-g",
        "--glob",
        metavar="PATTERN",
        help="Glob pattern to filter files (e.g., '*.py').",
    )
    replace_parser.add_argument(
        "-t",
        "--type",
        metavar="TYPE",
        help="File type filter (e.g., 'py', 'js'). Uses ripgrep's --type.",
    )
    replace_parser.add_argument(
        "--path",
        default=".",
        help="Directory or file to search in (default: current directory).",
    )
    replace_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output showing each file processed.",
    )
    replace_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Quiet mode - only show errors.",
    )
    replace_parser.add_argument(
        "-a",
        "--analyze",
        action="store_true",
        help="Analyze mode - show statistics about matches without making changes.",
    )
    replace_parser.add_argument(
        "-s",
        "--show-stats",
        action="store_true",
        help="Show detailed statistics after replacements.",
    )
    replace_parser.add_argument(
        "-b",
        "--blank-on-delete",
        action="store_true",
        help="Leave blank line when deleting (default: pull up line below).",
    )

    args = parser.parse_args(argv)

    if args.command == "ls":
        from . import lister
        return lister.run_lister(args)
    elif args.command == "replace":
        from . import replacer
        return replacer.run_replacer(args)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
