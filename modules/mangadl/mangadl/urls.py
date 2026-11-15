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
        default=Path("all-url-files.txt"),
        help="Output URL file (default: all-url-files.txt in the input folder).",
    )
    parser.add_argument(
        "-f",
        "--apply",
        action="store_true",
        default=False,
        help="Write or update the output URL file (default: dry-run preview).",
    )
    parser.add_argument(
        "-K",
        "--keep-duplicates",
        action="store_true",
        default=False,
        help="Keep repeated URL rows in the output (default: deduplicate).",
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


def _read_url_lines(path: Path) -> list[str]:
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        url = line.strip()
        if not url or url.startswith(("#", ";")):
            continue
        urls.append(url)
    return urls


def _collect_urls(
    source_files: list[Path],
    *,
    keep_duplicates: bool,
    existing_urls: list[str] | None = None,
) -> tuple[list[str], int, int]:
    urls: list[str] = list(existing_urls or [])
    existing_seen: set[str] = set(urls)
    seen: set[str] = set(urls)
    duplicate_count = 0
    new_count = 0
    for path in source_files:
        for url in _read_url_lines(path):
            if existing_urls is not None and keep_duplicates and url in existing_seen:
                duplicate_count += 1
                continue
            if url in seen:
                duplicate_count += 1
                if not keep_duplicates:
                    continue
            else:
                seen.add(url)
            urls.append(url)
            new_count += 1
    return urls, duplicate_count, new_count


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

    existing_urls = _read_url_lines(output) if output.is_file() else None
    urls, duplicate_count, new_count = _collect_urls(
        source_files,
        keep_duplicates=args.keep_duplicates,
        existing_urls=existing_urls,
    )
    print(f"Mode: {'Apply' if args.apply else 'Dry run'}")
    print("Matched files:")
    for path in source_files:
        print(f"  {path}")
    print(f"Output: {output}")
    if existing_urls is not None:
        print(f"Existing URLs in output: {len(existing_urls)}")
        print(f"New URLs to add: {new_count}")
    print(f"URLs in output: {len(urls)}")
    duplicate_label = (
        "Duplicate rows found" if args.keep_duplicates else "Duplicates removed"
    )
    print(f"{duplicate_label}: {duplicate_count}")

    if args.apply:
        _write_urls(output, urls)
        action_verb = "updated" if existing_urls is not None else "written"
        print(f"Combined URL file {action_verb}.")
    else:
        print("Dry run only; no files were written.")
    return 0
