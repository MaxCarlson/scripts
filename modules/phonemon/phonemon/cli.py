#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from .ui import run_curses


def build_parser() -> argparse.ArgumentParser:
    """
    Build the CLI argument parser.

    Exposes:
      -r / --refresh : refresh interval in seconds (float, default 0.5)
      -t / --top     : number of top processes to show (int, default 5)
      -m / --mode    : initial mode: overview|cpu|procs (default overview)
      -v / --verbose : reserved (no-op in curses mode)
      -q / --quiet   : reserved (no-op in curses mode)
    """
    p = argparse.ArgumentParser(
        prog="phonemon",
        description="Phone-friendly resource monitor TUI (Termux-ready), similar to btop.",
    )
    p.add_argument(
        "-r", "--refresh",
        type=float,
        default=0.5,
        help="Refresh interval in seconds (default: 0.5)",
    )
    p.add_argument(
        "-t", "--top",
        type=int,
        default=5,
        help="Top N processes to show where applicable (default: 5)",
    )
    p.add_argument(
        "-m", "--mode",
        choices=["overview", "cpu", "procs"],
        default="overview",
        help="Start in a specific mode (default: overview)",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="(reserved) Verbose logs (not used in curses mode).",
    )
    p.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="(reserved) Suppress non-critical logs (not used in curses mode).",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    """
    Console entrypoint used by the `phonemon` script and `python -m phonemon`.
    """
    args = build_parser().parse_args(argv)
    try:
        run_curses(
            topn=max(1, args.top),
            refresh=max(0.1, args.refresh),
            start_mode=args.mode,
        )
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
