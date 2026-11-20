#!/usr/bin/env python3
"""Canonical text and clipboard-vs-file comparison helpers."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


EXIT_EQUAL = 0
EXIT_DIFFERENT = 1
EXIT_ERROR = 2


@dataclass(frozen=True)
class ComparisonResult:
    """Structured result of comparing a file (or target text) with clipboard text."""

    equal: bool
    exit_code: int
    strict: bool
    ignore_trailing_newline: bool
    encoding: str
    file_chars: int
    clipboard_chars: int
    file_lines: int
    clipboard_lines: int
    line_ending_mismatch: bool
    trailing_newline_mismatch: bool
    similarity_ratio: float
    diff_lines: tuple[str, ...]
    error: Optional[str] = None
    diagnostics: tuple[str, ...] = ()


def _normalize_text(text: str, *, ignore_trailing_newline: bool) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if ignore_trailing_newline:
        normalized = normalized.rstrip("\n")
    return normalized


def _detect_eol(text: str) -> str:
    if "\r\n" in text:
        return "CRLF"
    if "\n" in text:
        return "LF"
    if "\r" in text:
        return "CR"
    return "NONE"


def compare_texts(
    file_text: str,
    clipboard_text: str,
    *,
    strict: bool = False,
    ignore_trailing_newline: bool = False,
    encoding: str = "utf-8",
    context_lines: int = 3,
    from_label: str = "file",
    to_label: str = "clipboard",
) -> ComparisonResult:
    """Compare two strings in either strict or normalized mode."""
    eol_file = _detect_eol(file_text)
    eol_clip = _detect_eol(clipboard_text)
    line_ending_mismatch = eol_file != eol_clip and "NONE" not in (eol_file, eol_clip)
    trailing_newline_mismatch = file_text.endswith("\n") != clipboard_text.endswith("\n")

    if strict:
        left = file_text
        right = clipboard_text
        left_lines = file_text.splitlines(keepends=True)
        right_lines = clipboard_text.splitlines(keepends=True)
    else:
        left = _normalize_text(file_text, ignore_trailing_newline=ignore_trailing_newline)
        right = _normalize_text(clipboard_text, ignore_trailing_newline=ignore_trailing_newline)
        left_lines = left.splitlines()
        right_lines = right.splitlines()

    equal = left == right
    diff_lines = tuple(
        difflib.unified_diff(
            [ln.rstrip("\r\n") for ln in left_lines] if strict else left_lines,
            [ln.rstrip("\r\n") for ln in right_lines] if strict else right_lines,
            fromfile=from_label,
            tofile=to_label,
            lineterm="",
            n=context_lines,
        )
    )
    ratio = difflib.SequenceMatcher(None, left, right).ratio()

    diagnostics: list[str] = []
    if line_ending_mismatch:
        diagnostics.append(f"Line ending mismatch: file={eol_file}, clipboard={eol_clip}")
    if trailing_newline_mismatch:
        diagnostics.append(
            f"Trailing newline mismatch: file={file_text.endswith(chr(10))}, "
            f"clipboard={clipboard_text.endswith(chr(10))}"
        )

    return ComparisonResult(
        equal=equal,
        exit_code=EXIT_EQUAL if equal else EXIT_DIFFERENT,
        strict=strict,
        ignore_trailing_newline=ignore_trailing_newline,
        encoding=encoding,
        file_chars=len(file_text),
        clipboard_chars=len(clipboard_text),
        file_lines=len(file_text.splitlines()),
        clipboard_lines=len(clipboard_text.splitlines()),
        line_ending_mismatch=line_ending_mismatch,
        trailing_newline_mismatch=trailing_newline_mismatch,
        similarity_ratio=ratio,
        diff_lines=diff_lines,
        diagnostics=tuple(diagnostics),
    )


def compare_clipboard_to_file(
    file_path: Path | str,
    get_clipboard_fn: Callable[[], str],
    *,
    strict: bool = False,
    ignore_trailing_newline: bool = False,
    encoding: str = "utf-8",
    context_lines: int = 3,
) -> ComparisonResult:
    """Read a file with encoding diagnostics, fetch clipboard, and compare."""
    path = Path(file_path)
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        return ComparisonResult(
            equal=False,
            exit_code=EXIT_ERROR,
            strict=strict,
            ignore_trailing_newline=ignore_trailing_newline,
            encoding=encoding,
            file_chars=0,
            clipboard_chars=0,
            file_lines=0,
            clipboard_lines=0,
            line_ending_mismatch=False,
            trailing_newline_mismatch=False,
            similarity_ratio=0.0,
            diff_lines=(),
            error=f"Could not read file '{path}': {exc}",
        )

    try:
        file_text = raw_bytes.decode(encoding)
    except UnicodeDecodeError as exc:
        return ComparisonResult(
            equal=False,
            exit_code=EXIT_ERROR,
            strict=strict,
            ignore_trailing_newline=ignore_trailing_newline,
            encoding=encoding,
            file_chars=0,
            clipboard_chars=0,
            file_lines=0,
            clipboard_lines=0,
            line_ending_mismatch=False,
            trailing_newline_mismatch=False,
            similarity_ratio=0.0,
            diff_lines=(),
            error=(
                f"Encoding error decoding '{path}' as {encoding} at byte {exc.start}: "
                f"{exc.reason}. Try --encoding with the file's actual encoding."
            ),
            diagnostics=(f"UTF-8/encoding decode failure at byte offset {exc.start}-{exc.end}",),
        )

    try:
        clipboard_text = get_clipboard_fn()
    except Exception as exc:
        return ComparisonResult(
            equal=False,
            exit_code=EXIT_ERROR,
            strict=strict,
            ignore_trailing_newline=ignore_trailing_newline,
            encoding=encoding,
            file_chars=len(file_text),
            clipboard_chars=0,
            file_lines=len(file_text.splitlines()),
            clipboard_lines=0,
            line_ending_mismatch=False,
            trailing_newline_mismatch=False,
            similarity_ratio=0.0,
            diff_lines=(),
            error=f"Failed to read clipboard: {exc}",
        )

    if clipboard_text is None or clipboard_text == "" or clipboard_text.strip() == "":
        return ComparisonResult(
            equal=False,
            exit_code=EXIT_ERROR,
            strict=strict,
            ignore_trailing_newline=ignore_trailing_newline,
            encoding=encoding,
            file_chars=len(file_text),
            clipboard_chars=0 if clipboard_text is None else len(clipboard_text),
            file_lines=len(file_text.splitlines()),
            clipboard_lines=0,
            line_ending_mismatch=False,
            trailing_newline_mismatch=False,
            similarity_ratio=0.0,
            diff_lines=(),
            error="Clipboard is empty or contains only whitespace.",
            diagnostics=("Empty or whitespace-only clipboard",),
        )

    return compare_texts(
        file_text,
        clipboard_text,
        strict=strict,
        ignore_trailing_newline=ignore_trailing_newline,
        encoding=encoding,
        context_lines=context_lines,
        from_label=f"file: {path}",
        to_label="clipboard",
    )
