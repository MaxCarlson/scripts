#!/usr/bin/env python3
"""
Remove a leading numeric prefix from each line in a text file.

Specifically, this script removes a prefix of the form:

    <one or more digits><period><space>

from the beginning of each line.

Example:
    "1211. Example line" -> "Example line"

The script updates the file in place by default. It can also create a backup
and supports a dry-run mode.

Examples:
    python remove_leading_number_prefix.py -i input.txt
    python remove_leading_number_prefix.py -i input.txt -b
    python remove_leading_number_prefix.py -i input.txt -n -v
"""
__version__ = "0.1.0"

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path


LEADING_NUMBER_PREFIX_PATTERN = re.compile(r"^\d+\. ")


def build_argument_parser() -> argparse.ArgumentParser:
    """
    Build and return the command-line argument parser.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Remove a leading '<digits>. ' prefix from the beginning of each line "
            "in a text file and replace the original file in place."
        )
    )
    parser.add_argument(
        "-i",
        "--input-file",
        required=True,
        help="Path to the input text file to modify in place.",
    )
    parser.add_argument(
        "-e",
        "--encoding",
        default="utf-8",
        help="Text encoding to use when reading and writing the file. Default: utf-8",
    )
    parser.add_argument(
        "-b",
        "--backup",
        action="store_true",
        help="Create a .bak backup file before replacing the original file.",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Preview the transformed content to stdout without modifying the file.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print detailed status information to stderr.",
    )
    return parser


def remove_leading_number_prefix_from_line(line: str) -> str:
    """
    Remove a leading '<digits>. ' prefix from a single line.

    Only removes the prefix if it appears at the very start of the line.

    Args:
        line: The input line.

    Returns:
        The transformed line.
    """
    return LEADING_NUMBER_PREFIX_PATTERN.sub("", line, count=1)


def transform_text(text: str) -> str:
    """
    Transform the entire file content line by line while preserving line endings.

    Args:
        text: Full file content.

    Returns:
        Transformed file content.
    """
    return "".join(
        remove_leading_number_prefix_from_line(line)
        for line in text.splitlines(keepends=True)
    )


def validate_input_file(file_path: Path) -> None:
    """
    Validate that the provided path exists and is a regular file.

    Args:
        file_path: File path to validate.

    Raises:
        FileNotFoundError: If the file does not exist.
        IsADirectoryError: If the path is a directory instead of a file.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {file_path}")
    if not file_path.is_file():
        raise IsADirectoryError(f"Input path is not a regular file: {file_path}")


def write_text_atomically(
    destination_path: Path,
    content: str,
    encoding: str,
) -> None:
    """
    Write text to a file atomically by writing to a temporary file first.

    Args:
        destination_path: Path to replace.
        content: Content to write.
        encoding: Encoding to use.
    """
    temp_fd, temp_path_str = tempfile.mkstemp(
        dir=str(destination_path.parent),
        prefix=f"{destination_path.name}.",
        suffix=".tmp",
        text=True,
    )

    temp_path = Path(temp_path_str)

    try:
        with open(temp_fd, "w", encoding=encoding, newline="") as temp_file:
            temp_file.write(content)
        temp_path.replace(destination_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise


def create_backup_file(file_path: Path, encoding: str, verbose: bool) -> Path:
    """
    Create a backup copy of the input file next to the original.

    Args:
        file_path: Original file path.
        encoding: Encoding to use for read/write.
        verbose: Whether to log extra details.

    Returns:
        The backup file path.
    """
    backup_path = file_path.with_suffix(file_path.suffix + ".bak")
    original_content = file_path.read_text(encoding=encoding)
    backup_path.write_text(original_content, encoding=encoding, newline="")
    if verbose:
        print(f"Created backup: {backup_path}", file=sys.stderr)
    return backup_path


def process_file(
    input_file: Path,
    encoding: str = "utf-8",
    create_backup: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
) -> int:
    """
    Process a file by removing the leading numeric prefix from each line.

    Args:
        input_file: File to process.
        encoding: File encoding.
        create_backup: Whether to create a .bak file first.
        dry_run: Whether to preview instead of modifying.
        verbose: Whether to emit extra logs.

    Returns:
        Process exit code. Zero indicates success.
    """
    validate_input_file(input_file)

    if verbose:
        print(f"Reading file: {input_file}", file=sys.stderr)

    original_content = input_file.read_text(encoding=encoding)
    transformed_content = transform_text(original_content)

    if dry_run:
        if verbose:
            print("Dry-run mode enabled; original file will not be modified.", file=sys.stderr)
        sys.stdout.write(transformed_content)
        return 0

    if create_backup:
        create_backup_file(
            file_path=input_file,
            encoding=encoding,
            verbose=verbose,
        )

    if verbose:
        print(f"Writing updated content to: {input_file}", file=sys.stderr)

    write_text_atomically(
        destination_path=input_file,
        content=transformed_content,
        encoding=encoding,
    )

    if verbose:
        print("File updated successfully.", file=sys.stderr)

    return 0


def main() -> int:
    """
    Entry point for the command-line interface.

    Returns:
        Process exit code.
    """
    parser = build_argument_parser()
    args = parser.parse_args()

    try:
        return process_file(
            input_file=Path(args.input_file),
            encoding=args.encoding,
            create_backup=args.backup,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
