"""Dry-run-first merging of matching URL-list files."""

from __future__ import annotations

import argparse
import glob
import os
import tempfile
from pathlib import Path
from typing import Callable


def configure_parser(
    parser: argparse.ArgumentParser, *, path_type: Callable[[str], Path]
) -> None:
    parser.add_argument(
        "-d",
        "--directory",
        type=path_type,
        default=Path("."),
        help="Folder containing URL files (default: current directory).",
    )
    parser.add_argument(
        "-p",
        "--pattern",
        action="append",
        required=True,
        metavar="GLOB",
        help="File-name pattern to include; repeat to add patterns, e.g. urls*.txt.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("combined_urls.txt"),
        help="Output URL file (default: combined_urls.txt in the input folder).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "-n",
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="List matched files and preview the merge without writing (default).",
    )
    mode.add_argument(
        "-f",
        "--apply",
        dest="dry_run",
        action="store_false",
        help="Write the combined URL file.",
    )
    duplicate_action = parser.add_mutually_exclusive_group()
    duplicate_action.add_argument(
        "-N",
        "--no-duplicates",
        dest="no_duplicates",
        action="store_true",
        default=True,
        help="Keep only the first copy of each URL (default).",
    )
    duplicate_action.add_argument(
        "-K",
        "--keep-duplicates",
        dest="no_duplicates",
        action="store_false",
        help="Keep repeated URL rows in the output.",
    )


def _output_path(value: Path, directory: Path) -> Path:
    expanded = value.expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    if expanded.parent == Path("."):
        return (directory / expanded).resolve()
    return expanded.resolve()


def _matching_files(directory: Path, patterns: list[str]) -> list[Path]:
    matches: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        candidate = Path(pattern).expanduser()
        search = candidate if candidate.is_absolute() else directory / candidate
        pattern_matches = {
            Path(match).resolve()
            for match in glob.glob(str(search))
            if Path(match).is_file()
        }
        for path in sorted(
            pattern_matches, key=lambda item: (str(item).casefold(), str(item))
        ):
            if path not in seen:
                matches.append(path)
                seen.add(path)
    return matches


def _collect_urls(
    source_files: list[Path], *, no_duplicates: bool
) -> tuple[list[str], int]:
    urls: list[str] = []
    seen: set[str] = set()
    duplicate_count = 0
    for path in source_files:
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            url = line.strip()
            if not url or url.startswith(("#", ";")):
                continue
            if url in seen:
                duplicate_count += 1
                if no_duplicates:
                    continue
            else:
                seen.add(url)
            urls.append(url)
    return urls, duplicate_count


def _write_urls(path: Path, urls: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            if urls:
                stream.write("\n".join(urls) + "\n")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def run_cli(args: argparse.Namespace) -> int:
    directory = Path(args.directory).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f"URL-file directory does not exist: {directory}")

    output = _output_path(args.output, directory)
    source_files = _matching_files(directory, args.pattern)
    if not source_files:
        raise ValueError("No URL files matched the supplied patterns.")
    if output in source_files:
        raise ValueError(
            f"The output file is also matched as an input: {output}. Choose a different output path or pattern."
        )

    urls, duplicate_count = _collect_urls(
        source_files, no_duplicates=args.no_duplicates
    )
    print(f"Mode: {'Dry run' if args.dry_run else 'Apply'}")
    print("Matched files:")
    for path in source_files:
        print(f"  {path}")
    print(f"Output: {output}")
    print(f"URLs in output: {len(urls)}")
    duplicate_label = (
        "Duplicates removed" if args.no_duplicates else "Duplicate rows found"
    )
    print(f"{duplicate_label}: {duplicate_count}")

    if not args.dry_run:
        _write_urls(output, urls)
        print("Combined URL file written.")
    else:
        print("Dry run only; no files were written.")
    return 0
