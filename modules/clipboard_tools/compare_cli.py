"""Concise clipboard and pairwise file comparison command implementations."""

from __future__ import annotations

import argparse
import itertools
import os
import subprocess
from pathlib import Path
from typing import Sequence

from rich.console import Console
from rich.text import Text

from clipboard_tools.compare import (
    EXIT_DIFFERENT,
    EXIT_ERROR,
    EXIT_EQUAL,
    ComparisonResult,
    compare_clipboard_to_file,
    compare_files,
)

console = Console(soft_wrap=True)
stderr = Console(stderr=True, soft_wrap=True)


def get_clipboard() -> str:
    """Load the repository clipboard backend only for the clipboard command."""
    from cross_platform.clipboard_utils import get_clipboard as read_clipboard

    return read_clipboard()


def _character_count(count: int) -> str:
    noun = "character" if count == 1 else "characters"
    return f"{count} {noun}"


def format_summary(
    result: ComparisonResult,
    first_name: str,
    second_name: str,
    *,
    first_label: str = "file",
    second_label: str = "file",
) -> str:
    """Describe equality and the character-count size difference for a pair."""
    if result.error:
        return f"{first_name} vs {second_name}: ERROR: {result.error}"

    first_size = result.file_chars
    second_size = result.clipboard_chars
    if result.equal:
        status = "Identical" if result.strict else "Identical (normalized)"
        return (
            f"{first_name} vs {second_name}: {status} - {first_label} {_character_count(first_size)}; "
            f"{second_label} {_character_count(second_size)}."
        )

    if first_size > second_size:
        larger_label, larger_size = first_label, first_size
        smaller_size = second_size
    elif second_size > first_size:
        larger_label, larger_size = second_label, second_size
        smaller_size = first_size
    else:
        return f"{first_name} vs {second_name}: Different - both are {_character_count(first_size)}."

    return (
        f"{first_name} vs {second_name}: Different - {larger_label} is larger by "
        f"{_character_count(larger_size - smaller_size)} ({larger_size} vs {smaller_size})."
    )


def clipboard_summary_main(argv: Sequence[str] | None = None) -> int:
    """Print a concise comparison between the clipboard and one target file."""
    parser = argparse.ArgumentParser(
        prog="cld",
        description="Summarize whether the clipboard and a target file match and which is larger.",
    )
    parser.add_argument("file", help="Target file to compare with the clipboard")
    parser.add_argument("-s", "--strict", action="store_true", help="Compare exact text including line endings.")
    parser.add_argument("-z", "--trim-trailing-newline", action="store_true", help="Ignore final newline differences.")
    parser.add_argument("-E", "--encoding", default="utf-8", help="Text encoding (default: utf-8).")
    parser.add_argument("-k", "--check", action="store_true", help="Exit 0 if equal, 1 if different, or 2 on error.")
    args = parser.parse_args(argv)

    result = compare_clipboard_to_file(
        args.file,
        get_clipboard,
        strict=args.strict,
        ignore_trailing_newline=args.trim_trailing_newline,
        encoding=args.encoding,
    )
    if result.error:
        stderr.print(f"[bold red]ERROR:[/] {result.error}")
        return EXIT_ERROR if args.check else 1

    print(
        format_summary(
            result,
            Path(args.file).name,
            "clipboard",
            first_label="target file",
            second_label="clipboard",
        )
    )
    return result.exit_code if args.check else EXIT_EQUAL


def _resolve_file_arguments(inputs: Sequence[str]) -> list[Path]:
    """Resolve ordinary paths or expand ``fd`` arguments as NUL-delimited paths."""
    if inputs[0].casefold() != "fd":
        return [Path(value) for value in inputs]
    if len(inputs) < 2:
        raise ValueError("Use 'comp fd <pattern>' with an fd search pattern.")

    command = ["fd", "--print0", *inputs[1:]]
    try:
        completed = subprocess.run(command, capture_output=True, check=False)
    except OSError as exc:
        raise ValueError(f"Could not run fd: {exc}") from exc

    if completed.returncode != 0:
        detail = completed.stderr.decode(errors="replace").strip()
        if completed.returncode == 1 and not completed.stdout:
            raise ValueError("fd found no files to compare.")
        raise ValueError(f"fd failed with exit code {completed.returncode}: {detail}")

    paths = [Path(os.fsdecode(value)) for value in completed.stdout.split(b"\0") if value]
    if not paths:
        raise ValueError("fd found no files to compare.")
    return paths


def _make_file_parser(program: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=program,
        description="Compare every pair of files; use 'fd <pattern>' in place of file paths to search.",
    )
    parser.add_argument("inputs", nargs="+", metavar="FILE", help="Two or more file paths, or fd <pattern>")
    parser.add_argument("-s", "--strict", action="store_true", help="Compare exact text including line endings.")
    parser.add_argument("-z", "--trim-trailing-newline", action="store_true", help="Ignore final newline differences.")
    parser.add_argument("-E", "--encoding", default="utf-8", help="Text encoding (default: utf-8).")
    parser.add_argument("-c", "--context-lines", type=int, default=3, help="Diff context lines (default: 3).")
    return parser


def _print_diff(result: ComparisonResult) -> None:
    for line in result.diff_lines:
        if line.startswith(("---", "+++")):
            console.print(line)
        elif line.startswith("@@"):
            console.print(Text(line, style="cyan"))
        elif line.startswith("-"):
            console.print(Text(line, style="red"))
        elif line.startswith("+"):
            console.print(Text(line, style="green"))
        else:
            console.print(line)
    if result.equal:
        console.print("No differences found.")


def compare_files_main(argv: Sequence[str] | None = None, *, detailed: bool = False) -> int:
    """Compare every unordered pair and print concise or detailed output."""
    parser = _make_file_parser("compd" if detailed else "comp")
    args = parser.parse_args(argv)
    try:
        paths = _resolve_file_arguments(args.inputs)
    except ValueError as exc:
        stderr.print(f"[bold red]ERROR:[/] {exc}")
        return EXIT_ERROR

    if len(paths) < 2:
        stderr.print("[bold red]ERROR:[/] At least two files are required for pairwise comparison.")
        return EXIT_ERROR

    comparisons: list[tuple[Path, Path, ComparisonResult]] = []
    had_error = False
    any_different = False
    for first, second in itertools.combinations(paths, 2):
        result = compare_files(
            first,
            second,
            strict=args.strict,
            ignore_trailing_newline=args.trim_trailing_newline,
            encoding=args.encoding,
            context_lines=args.context_lines,
        )
        comparisons.append((first, second, result))
        if result.error:
            had_error = True
            stderr.print(f"[bold red]ERROR:[/] {result.error}")
        elif not result.equal:
            any_different = True
        if detailed:
            console.print(f"\n[bold]{first} vs {second}[/]")
            _print_diff(result)

    console.print("\n[bold]Summary[/]")
    for first, second, result in comparisons:
        console.print(
            format_summary(
                result,
                str(first),
                str(second),
                first_label=str(first),
                second_label=str(second),
            )
        )

    if had_error:
        return EXIT_ERROR
    return EXIT_DIFFERENT if any_different else EXIT_EQUAL


def compare_main(argv: Sequence[str] | None = None) -> int:
    """Entry point for concise pairwise comparison."""
    return compare_files_main(argv)


def compare_detailed_main(argv: Sequence[str] | None = None) -> int:
    """Entry point for diff output followed by concise pairwise summaries."""
    return compare_files_main(argv, detailed=True)
