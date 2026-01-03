#!/usr/bin/env python3
"""Find-and-replace helper with ripgrep integration and safe dry-run previews."""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

MODULES_DIR = Path(__file__).resolve().parents[1] / "modules"
if MODULES_DIR.exists():
    sys.path.insert(0, str(MODULES_DIR))

try:
    from cross_platform.path_utils import (
        expand_path as cp_expand_path,
        to_posix_path as cp_to_posix_path,
        to_native_path as cp_to_native_path,
    )
    HAVE_CROSS_PLATFORM = True
except ImportError:  # pragma: no cover - fallback path when module missing
    HAVE_CROSS_PLATFORM = False


THEME = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "danger": "bold red",
        "path": "bold green",
        "line_num": "bold blue",
        "old": "bold red",
        "new": "bold green",
        "summary": "bold blue",
    }
)
console = Console(theme=THEME)

DEFAULT_EXCLUSIONS = [".git", ".svn", ".hg", "__pycache__"]


def build_parser() -> argparse.ArgumentParser:
    """Configure the CLI parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Search for a pattern (default) or preview/apply replacements with diff output.\n"
            "The pattern is treated as a literal unless --regex is supplied."
        )
    )
    parser.add_argument("pattern", help="Pattern to search for.")
    parser.add_argument(
        "replacement",
        nargs="?",
        help="Replacement text. When omitted, the tool simply streams ripgrep output.",
    )
    parser.add_argument(
        "-p",
        "--path",
        action="append",
        help="File/directory/glob to search. Repeat for multiple roots (defaults to current directory).",
    )
    parser.add_argument(
        "-w",
        "--write",
        action="store_true",
        help="Write the replacements to disk. Dry-run preview is the default.",
    )
    parser.add_argument(
        "-i",
        "--ignore-case",
        action="store_true",
        help="Perform a case-insensitive search.",
    )
    parser.add_argument(
        "-x",
        "--exclude",
        nargs="+",
        help="Files/directories/globs to exclude in addition to the defaults.",
    )
    parser.add_argument(
        "--regex",
        action="store_true",
        help="Treat the pattern as a regular expression (default is literal text).",
    )
    parser.add_argument(
        "--rg-bin",
        default="rg",
        help="Path to the ripgrep executable (defaults to 'rg').",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show per-file replacement counts during previews.",
    )
    parser.add_argument(
        "--no-path-normalize",
        action="store_true",
        help="Do not auto-convert Windows/Linux path separators or env vars.",
    )
    return parser


# ---------------------------------------------------------------------------
# Ripgrep helpers
# ---------------------------------------------------------------------------


def looks_like_glob(path_value: str) -> bool:
    """Return True when the argument contains glob characters."""
    return any(ch in path_value for ch in ("*", "?", "[", "]"))


def expand_path(value: str, *, normalize: bool) -> str:
    """Expand environment variables with the shared helpers when possible."""
    if not normalize:
        return os.path.expanduser(os.path.expandvars(value))
    if HAVE_CROSS_PLATFORM:
        return cp_expand_path(value)
    return os.path.expanduser(os.path.expandvars(value))


def to_posix(value: str, *, normalize: bool) -> str:
    if not normalize:
        return value
    if HAVE_CROSS_PLATFORM:
        return cp_to_posix_path(value)
    return expand_path(value, normalize=normalize).replace("\\", "/")


def to_native(value: str, *, normalize: bool) -> str:
    if not normalize:
        return os.path.expanduser(os.path.expandvars(value))
    if HAVE_CROSS_PLATFORM:
        return cp_to_native_path(value)
    expanded = expand_path(value, normalize=normalize)
    if os.name == "nt":
        return expanded.replace("/", "\\")
    return expanded.replace("\\", "/")


def normalize_for_rg(value: str, *, normalize: bool) -> str:
    """
    Convert a user-supplied path so ripgrep can understand it on any platform.

    On Windows this turns backslashes into forward slashes, which matches how
    ripgrep formats paths in the sample output from the user.
    """
    candidate = to_posix(value, normalize=normalize)
    if looks_like_glob(candidate):
        return candidate
    try:
        resolved = Path(to_native(value, normalize=normalize)).resolve()
        return resolved.as_posix()
    except OSError:
        return candidate


def normalize_for_fs(value: str, *, normalize: bool) -> str:
    """Normalize input paths for Python's file-system APIs."""
    expanded = to_native(value, normalize=normalize)
    return expanded or value


def run_subprocess(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Wrapper to simplify mocking during tests."""
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


@dataclass
class SearchSummary:
    """Accumulates statistics produced by ripgrep."""

    files: set = field(default_factory=set)
    lines: set = field(default_factory=set)
    matches: int = 0

    def register(self, file_path: str, line_number: int, count: int) -> None:
        self.files.add(file_path)
        self.lines.add((file_path, line_number))
        self.matches += count


class RipgrepRunner:
    """Runs ripgrep in the background to gather search stats and colored output."""

    def __init__(self, args: argparse.Namespace, runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] = run_subprocess):
        self.args = args
        self.runner = runner
        self.normalize_paths = not args.no_path_normalize
        self.search_paths = [normalize_for_rg(p, normalize=self.normalize_paths) for p in (args.path or ["."])]
        self.exclusions = list(args.exclude or []) + DEFAULT_EXCLUSIONS

    def _base_cmd(self) -> List[str]:
        cmd = [self.args.rg_bin, "--line-number", "--column"]
        if self.args.ignore_case:
            cmd.append("--ignore-case")
        if not self.args.regex:
            cmd.append("--fixed-strings")
        for pattern in self.exclusions:
            cmd.extend(["--glob", f"!{pattern}"])
        return cmd

    def stream_colored_output(self) -> int:
        """Run rg to produce the familiar colored output, streaming live output."""
        cmd = self._base_cmd()
        cmd.append("--color=always")
        cmd.append(self.args.pattern)
        cmd.extend(self.search_paths or ["."])
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            console.print("Error: ripgrep executable not found. Install rg or provide --rg-bin.", style="danger")
            return 2

        try:
            if proc.stdout:
                for line in proc.stdout:
                    sys.stdout.write(line)
                    sys.stdout.flush()
        finally:
            if proc.stdout:
                proc.stdout.close()

        stderr_text = ""
        if proc.stderr:
            stderr_text = proc.stderr.read()
            proc.stderr.close()

        returncode = proc.wait()

        if stderr_text:
            console.print(stderr_text, style="warning")

        return returncode

    def files_with_matches(self) -> Tuple[List[Path], int]:
        """Return a list of files that contain matches using ripgrep."""
        cmd = self._base_cmd()
        cmd.append("--files-with-matches")
        cmd.append("--null")
        cmd.append(self.args.pattern)
        cmd.extend(self.search_paths or ["."])

        try:
            result = self.runner(cmd)
        except FileNotFoundError:
            console.print("Error: ripgrep executable not found. Install rg or provide --rg-bin.", style="danger")
            return [], 2

        files: List[Path] = []
        for raw in result.stdout.split("\0"):
            if raw:
                files.append(Path(raw))
        if result.stderr:
            console.print(result.stderr, style="warning")
        return files, result.returncode

    def gather_summary(self) -> Tuple[SearchSummary, int]:
        """Run rg --json so we can provide totals that match the preview."""
        cmd = self._base_cmd()
        cmd.append("--json")
        cmd.append("--color=never")
        cmd.append(self.args.pattern)
        cmd.extend(self.search_paths or ["."])
        try:
            result = self.runner(cmd)
        except FileNotFoundError:
            console.print("Error: ripgrep executable not found. Install rg or provide --rg-bin.", style="danger")
            return SearchSummary(), 2

        summary = SearchSummary()
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") != "match":
                continue
            data = payload["data"]
            path = data["path"]["text"]
            line_number = data["line_number"]
            summary.register(path, line_number, len(data.get("submatches", [])))
        if result.stderr:
            console.print(result.stderr, style="warning")
        return summary, result.returncode


# ---------------------------------------------------------------------------
# Replacement mechanics
# ---------------------------------------------------------------------------


@dataclass
class LineMatch:
    """Stores a single match relative to a specific line."""

    start: int
    end: int
    replacement: str
    original: str


class LineIndex:
    """Maps absolute offsets to line numbers and makes display formatting easy."""

    def __init__(self, content: str):
        self.lines: List[str] = []
        self.starts: List[int] = []
        offset = 0
        for raw in content.splitlines(keepends=True):
            self.lines.append(raw.rstrip("\n").rstrip("\r"))
            self.starts.append(offset)
            offset += len(raw)
        if content and content[-1] not in ("\n", "\r"):
            # splitlines keeps the last line even without a newline, so nothing extra is required.
            pass

    def line_at(self, index: int) -> Tuple[int, str, int]:
        """
        Return (line_number, line_text, line_start_offset) for the provided absolute index.
        Line numbers are 1-based to match editors and ripgrep output.
        """
        if not self.starts:
            raise ValueError("File is empty.")
        position = bisect_right(self.starts, index) - 1
        line_no = position + 1
        line_text = self.lines[position]
        line_start = self.starts[position]
        return line_no, line_text, line_start


@dataclass
class ReplacementStats:
    """Tracks cumulative replacement data for the final summary."""

    files: int = 0
    lines: int = 0
    replacements: int = 0

    def update(self, file_lines: int, replacements: int) -> None:
        self.files += 1
        self.lines += file_lines
        self.replacements += replacements


class ReplacementRunner:
    """Implements the dry-run diff previews and eventual writes."""

    def __init__(self, args: argparse.Namespace, candidate_files: Optional[Sequence[Path]] = None):
        if args.replacement is None:
            raise ValueError("ReplacementRunner requires a replacement value.")
        self.args = args
        self.normalize_paths = not args.no_path_normalize
        self.exclusions = list(args.exclude or []) + DEFAULT_EXCLUSIONS
        self.pattern = args.pattern
        self.replacement = args.replacement
        if candidate_files is None:
            self.candidate_files: Optional[List[Path]] = None
        else:
            self.candidate_files = [Path(p) for p in candidate_files]
        flags = re.IGNORECASE if args.ignore_case else 0
        if args.regex:
            self.compiled = re.compile(self.pattern, flags)
            self.replacement_func = self._regex_replacement
        else:
            escaped = re.escape(self.pattern)
            self.compiled = re.compile(escaped, flags)
            self.replacement_func = self._literal_replacement

    def _literal_replacement(self, match: re.Match) -> str:
        return self.replacement

    def _regex_replacement(self, match: re.Match) -> str:
        return match.expand(self.replacement)

    def iter_target_files(self) -> Iterable[Path]:
        """Yield every candidate file that matches the user's path filters."""
        if self.candidate_files is not None:
            yielded = set()
            for file_path in self.candidate_files:
                resolved = file_path.resolve()
                if resolved not in yielded:
                    yielded.add(resolved)
                    yield resolved
            return

        yielded = set()
        glob_options = self.args.path or ["."]
        for raw in glob_options:
            expanded = normalize_for_fs(raw, normalize=self.normalize_paths)
            if looks_like_glob(raw):
                matches = [Path(match) for match in glob.glob(expanded, recursive=True)]
            else:
                matches = [Path(expanded)]
            if not matches:
                console.print(f"Warning: Path does not exist: {raw}", style="warning")
                continue

            for entry in matches:
                if not entry.exists():
                    console.print(f"Warning: Path does not exist: {entry}", style="warning")
                    continue
                if self._is_excluded(entry):
                    continue
                if entry.is_file():
                    resolved = entry.resolve()
                    if resolved not in yielded:
                        yielded.add(resolved)
                        yield resolved
                    continue

                for root, dirs, files in os.walk(entry):
                    root_path = Path(root)
                    dirs[:] = [d for d in dirs if not self._is_excluded(root_path / d)]
                    for name in files:
                        file_path = root_path / name
                        if self._is_excluded(file_path):
                            continue
                        resolved = file_path.resolve()
                        if resolved in yielded:
                            continue
                        yielded.add(resolved)
                        yield resolved

    def _is_excluded(self, path_obj: Path) -> bool:
        """Return True for excluded directories or files."""
        for part in path_obj.parts:
            if part in DEFAULT_EXCLUSIONS:
                return True
        for pattern in self.exclusions:
            if path_obj.match(pattern):
                return True
        return False

    def run(self) -> ReplacementStats:
        """Execute the replacement workflow."""
        mode = "Dry run" if not self.args.write else "Applying changes"
        console.print(f"--- {mode} ---", style="info")
        stats = ReplacementStats()

        for file_path in self.iter_target_files():
            result = self._process_file(file_path)
            if not result:
                continue

            stats.update(result["line_count"], result["match_count"])
            self._display_file_result(file_path, result)

            if self.args.write:
                file_path.write_text(result["new_content"], encoding="utf-8")

        return stats

    def _process_file(self, file_path: Path) -> Optional[Dict]:
        """Run replacements for a single file and return data for display."""
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            console.print(f"Warning: Could not read {file_path}: {exc}", style="warning")
            return None

        matches = list(self.compiled.finditer(content))
        if not matches:
            return None

        replacer_lines = LineIndex(content)
        line_matches: Dict[int, List[LineMatch]] = {}
        for match in matches:
            try:
                line_no, _, line_start = replacer_lines.line_at(match.start())
            except ValueError:
                continue
            start = match.start() - line_start
            end = match.end() - line_start
            replacement_text = self.replacement_func(match)
            info = LineMatch(start, end, replacement_text, match.group(0))
            line_matches.setdefault(line_no, []).append(info)

        new_content = self._build_new_content(content, matches)
        return {
            "match_count": len(matches),
            "line_count": len(line_matches),
            "line_matches": line_matches,
            "lines": replacer_lines,
            "new_content": new_content,
        }

    def _build_new_content(self, content: str, matches: List[re.Match]) -> str:
        """Return the updated file contents after applying all replacements."""
        pieces: List[str] = []
        last = 0
        for match in matches:
            pieces.append(content[last: match.start()])
            pieces.append(self.replacement_func(match))
            last = match.end()
        pieces.append(content[last:])
        return "".join(pieces)

    def _display_file_result(self, file_path: Path, result: Dict) -> None:
        """Render the per-file diff style output."""
        console.print(f"\n{file_path.as_posix()}", style="path")
        if self.args.verbose:
            console.print(
                f"  {result['match_count']} replacements across {result['line_count']} line(s)",
                style="info",
            )

        for line_no in sorted(result["line_matches"].keys()):
            line_text = result["lines"].lines[line_no - 1]
            matches = sorted(result["line_matches"][line_no], key=lambda m: m.start)
            old_line = self._highlight_old_line(line_no, line_text, matches)
            new_line = self._highlight_new_line(line_no, line_text, matches)
            console.print(old_line)
            console.print(new_line)

    def _highlight_old_line(self, line_no: int, text_value: str, matches: List[LineMatch]) -> Text:
        """Return a Text object showing the original line with red highlights."""
        prefix = Text(f"- {line_no}: ", style="line_num")
        line_text = Text(text_value)
        for match in reversed(matches):
            line_text.stylize("old", match.start, match.end)
        line_text.stylize("old", 0, len(line_text))
        return prefix + line_text

    def _highlight_new_line(self, line_no: int, text_value: str, matches: List[LineMatch]) -> Text:
        """Return a Text object showing the replaced line with green highlights."""
        new_text_parts: List[str] = []
        cursor = 0
        highlight_ranges: List[Tuple[int, int]] = []
        new_length = 0
        for match in matches:
            new_text_parts.append(text_value[cursor: match.start])
            new_length += len(text_value[cursor: match.start])
            replacement = match.replacement
            start = new_length
            new_text_parts.append(replacement)
            new_length += len(replacement)
            highlight_ranges.append((start, new_length))
            cursor = match.end
        new_text_parts.append(text_value[cursor:])
        new_line_text = "".join(new_text_parts)

        prefix = Text(f"+ {line_no}: ", style="line_num")
        line_text = Text(new_line_text)
        for start, end in reversed(highlight_ranges):
            line_text.stylize("new", start, end)
        line_text.stylize("new", 0, len(line_text))
        return prefix + line_text


# ---------------------------------------------------------------------------
# Shared summary helpers
# ---------------------------------------------------------------------------


def print_summary(stats: ReplacementStats, dry_run: bool, mode: str) -> None:
    """Print a concise summary similar to ripgrep's statistics."""
    header = "Search Summary" if mode == "search" else "Replacement Summary"
    console.print(f"\n--- {header} ---", style="summary")
    table = Table(show_header=False, box=None)
    table.add_row("Files:", str(stats.files))
    table.add_row("Lines:", str(stats.lines))
    label = "Matches" if mode == "search" else "Replacements"
    table.add_row(f"{label}:", str(stats.replacements))
    console.print(table)

    if mode == "replace":
        if stats.replacements and dry_run:
            console.print("Dry run only. Re-run with --write to apply these changes.", style="warning")
        elif stats.replacements and not dry_run:
            console.print("Changes written to disk.", style="info")


def run_search_mode(args: argparse.Namespace) -> int:
    """Handle the ripgrep-only workflow."""
    runner = RipgrepRunner(args)
    display_code = runner.stream_colored_output()
    summary, summary_code = runner.gather_summary()
    stats = ReplacementStats(
        files=len(summary.files),
        lines=len(summary.lines),
        replacements=summary.matches,
    )
    print_summary(stats, dry_run=True, mode="search")
    return max(display_code, summary_code)


def run_replacement_mode(args: argparse.Namespace) -> int:
    """Handle diff previews and optional writes."""
    rg_runner = RipgrepRunner(args)
    display_code = rg_runner.stream_colored_output()
    files, file_code = rg_runner.files_with_matches()
    if display_code > 1:
        return display_code
    if file_code > 1:
        return file_code

    runner = ReplacementRunner(args, candidate_files=files)
    stats = runner.run()
    print_summary(stats, dry_run=not args.write, mode="replace")
    return 0 if file_code <= 1 else file_code


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.replacement is None and args.write:
        console.print("Error: --write requires both a pattern and a replacement.", style="danger")
        return 2

    if args.replacement is None:
        return run_search_mode(args)
    return run_replacement_mode(args)


if __name__ == "__main__":
    sys.exit(main())
