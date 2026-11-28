"""Flatten newline or NUL-delimited command output into one CSV record."""

from __future__ import annotations

import argparse
import csv
import io
import subprocess
import sys
from typing import Sequence

__version__ = "0.1.0"


def _records(value: str, *, null_input: bool) -> list[str]:
    parts = value.split("\0") if null_input else value.split("\n")
    return [part[:-1] if not null_input and part.endswith("\r") else part for part in parts if part]


def _flatten(values: Sequence[str], *, delimiter: str, quote_mode: str) -> str:
    buffer = io.StringIO(newline="")
    options = {
        "delimiter": delimiter,
        "lineterminator": "",
        "escapechar": "\\" if quote_mode == "none" else None,
        "quoting": {
            "minimal": csv.QUOTE_MINIMAL,
            "all": csv.QUOTE_ALL,
            "none": csv.QUOTE_NONE,
        }[quote_mode],
    }
    writer = csv.writer(buffer, **options)
    writer.writerow(values)
    return buffer.getvalue()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Flatten line or NUL-delimited input into one CSV record.")
    parser.add_argument("-d", "--delimiter", default=",", help="One-character CSV delimiter (default: comma).")
    parser.add_argument("-0", "--null-input", action="store_true", help="Split input on NUL instead of newlines.")
    parser.add_argument("-q", "--quote-mode", choices=("minimal", "all", "none"), default="minimal")
    parser.add_argument("-n", "--no-trailing-newline", action="store_true", help="Do not end output with a newline.")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Optional command after -- whose stdout is flattened.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if len(args.delimiter) != 1:
        parser.error("delimiter must be exactly one character")

    if args.command:
        command = args.command[1:] if args.command[0] == "--" else args.command
        if not command:
            parser.error("provide a command after --")
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
        except OSError as exc:
            print(f"flatten: could not run command: {exc}", file=sys.stderr)
            return 127
        if completed.stderr:
            print(completed.stderr, end="" if completed.stderr.endswith("\n") else "\n", file=sys.stderr)
        source = completed.stdout
        return_code = completed.returncode
    else:
        source = sys.stdin.read()
        return_code = 0

    output = _flatten(_records(source, null_input=args.null_input), delimiter=args.delimiter, quote_mode=args.quote_mode)
    sys.stdout.write(output)
    if not args.no_trailing_newline:
        sys.stdout.write("\n")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
