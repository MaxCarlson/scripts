#!/usr/bin/env python3
"""
filter-prune.py

A cross-platform deletion helper that combines fd-style path matching and
ripgrep-style content matching with dry-run-by-default safety.

Requires:
    - Python 3.9+
    - fd or fdfind for fd-based searches
    - rg for rg-based searches
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence


PROGRAM_NAME = "filter-prune.py"
VERSION = "1.1.0"
COMMAND_NAMES = {"fd", "rg"}
HELP_FLAGS = {"-h", "-?", "--help"}
VERSION_FLAGS = {"-V", "--version"}

OPERATION_KEYS = {
    "root",
    "delete",
    "yes",
    "quarantine_dir",
    "recursive",
    "allow_all",
    "limit",
    "json",
    "quiet",
    "verbose",
    "color",
}

FD_KEYS = {
    "entry_type",
    "glob_pattern",
    "extension",
    "exclude",
    "max_depth",
    "min_depth",
    "include_hidden",
    "no_ignore",
    "ignore_case",
    "follow_links",
}

RG_KEYS = {
    "content_pattern",
    "match_mode",
    "fixed_strings",
    "glob_pattern",
    "extension",
    "exclude",
    "max_depth",
    "min_depth",
    "include_hidden",
    "no_ignore",
    "ignore_case",
    "follow_links",
}


class SafePruneError(Exception):
    """Raised for expected user-facing errors."""


@dataclass(frozen=True)
class ToolConfig:
    """Executable resolution for external tools."""

    fd_executable: Optional[str]
    rg_executable: Optional[str]


@dataclass
class FilterTrace:
    """Verbose trace data for combined fd/rg filtering."""

    order: tuple[str, ...]
    fd_candidates: list[Path] = field(default_factory=list)
    rg_candidates: list[Path] = field(default_factory=list)
    filtered_by_fd: list[Path] = field(default_factory=list)
    filtered_by_rg: list[Path] = field(default_factory=list)


@dataclass
class OperationStats:
    """Summary of a dry-run, delete, or quarantine operation."""

    command: str
    dry_run: bool
    root: Path
    matched_count: int = 0
    would_be_affected_count: int = 0
    affected_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    targets: list[Path] = field(default_factory=list)
    would_be_affected: list[Path] = field(default_factory=list)
    affected: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    trace: Optional[FilterTrace] = None


@dataclass
class ParsedCli:
    """Parsed CLI state after composable subcommand parsing."""

    operation: argparse.Namespace
    order: tuple[str, ...]
    fd: Optional[argparse.Namespace]
    rg: Optional[argparse.Namespace]


class Ansi:
    """ANSI escape codes used for optional terminal color."""

    RESET = "\033[0m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    GREEN = "\033[32m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"
    DIM = "\033[2m"


def default_operation_args() -> argparse.Namespace:
    """Return default operation-level arguments."""
    return argparse.Namespace(
        root=".",
        delete=False,
        yes=False,
        quarantine_dir=None,
        recursive=False,
        allow_all=False,
        limit=None,
        json=False,
        quiet=False,
        verbose=False,
        color="auto",
    )


def default_fd_args() -> argparse.Namespace:
    """Return default fd-specific arguments."""
    return argparse.Namespace(
        entry_type="file",
        glob_pattern=[],
        extension=[],
        exclude=[],
        max_depth=None,
        min_depth=None,
        include_hidden=False,
        no_ignore=True,
        ignore_case=False,
        follow_links=False,
    )


def default_rg_args() -> argparse.Namespace:
    """Return default rg-specific arguments."""
    return argparse.Namespace(
        content_pattern=[],
        match_mode="all",
        fixed_strings=False,
        glob_pattern=[],
        extension=[],
        exclude=[],
        max_depth=None,
        min_depth=None,
        include_hidden=False,
        no_ignore=True,
        ignore_case=False,
        follow_links=False,
    )


def merge_namespace_values(target: argparse.Namespace, source: argparse.Namespace, allowed_keys: set[str]) -> None:
    """Merge selected argparse values into a target namespace."""
    for key, value in vars(source).items():
        if key in allowed_keys:
            setattr(target, key, value)


def normalize_extension(extension: str) -> str:
    """Normalize a file extension for fd/rg filtering."""
    cleaned = extension.strip()
    if cleaned.startswith("."):
        cleaned = cleaned[1:]
    if not cleaned:
        raise SafePruneError("Extension values cannot be empty.")
    return cleaned


def normalize_extensions(extensions: Optional[Sequence[str]]) -> list[str]:
    """Normalize a possibly repeated extension argument."""
    if not extensions:
        return []
    return [normalize_extension(extension) for extension in extensions]


def resolve_external_tool(candidates: Sequence[str]) -> Optional[str]:
    """Return the first executable found on PATH."""
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
    return None


def resolve_tool_config() -> ToolConfig:
    """Resolve supported external tool names."""
    return ToolConfig(
        fd_executable=resolve_external_tool(("fd", "fdfind")),
        rg_executable=resolve_external_tool(("rg",)),
    )


def ensure_tool_available(executable: Optional[str], tool_name: str) -> str:
    """Return an executable path or raise a helpful error."""
    if executable:
        return executable
    raise SafePruneError(
        f"Required tool '{tool_name}' was not found on PATH. "
        f"Install it first, then rerun this command."
    )


def resolve_root(root_value: str) -> Path:
    """Resolve the search root without requiring every child to exist."""
    root = Path(root_value).expanduser()
    if not root.exists():
        raise SafePruneError(f"Root path does not exist: {root}")
    if not root.is_dir():
        raise SafePruneError(f"Root path is not a directory: {root}")
    return root.resolve()


def is_path_inside_root(path: Path, root: Path) -> bool:
    """Return True when path is root or a descendant of root."""
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def relative_depth(path: Path, root: Path) -> int:
    """Return fd-like depth where a top-level child has depth 1."""
    try:
        relative = path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return 999999
    if str(relative) == ".":
        return 0
    return len(relative.parts)


def path_sort_key(path: Path) -> str:
    """Return a stable, case-insensitive path sort key."""
    return str(path).replace("\\", "/").lower()


def should_use_color(args: argparse.Namespace) -> bool:
    """Return True when colored terminal output should be used."""
    color_mode = getattr(args, "color", "auto")
    if color_mode == "always":
        return True
    if color_mode == "never":
        return False
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def colorize(text: str, color: str, args: argparse.Namespace) -> str:
    """Apply ANSI color when enabled."""
    if not should_use_color(args):
        return text
    return f"{color}{text}{Ansi.RESET}"


def parse_null_separated_paths(stdout: bytes, root: Path) -> list[Path]:
    """Parse NUL-separated command output into resolved paths."""
    paths: list[Path] = []
    for raw_part in stdout.split(b"\0"):
        if not raw_part:
            continue
        raw_text = raw_part.decode("utf-8", errors="replace")
        raw_path = Path(raw_text)
        path = raw_path if raw_path.is_absolute() else root / raw_path
        resolved = path.resolve(strict=False)
        if is_path_inside_root(resolved, root):
            paths.append(resolved)
    return paths


def run_external_command(command: Sequence[str], root: Path) -> list[Path]:
    """Run an external search command and parse NUL-separated paths."""
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SafePruneError(f"Executable not found: {command[0]}") from exc

    if completed.returncode not in (0, 1):
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        joined = " ".join(command)
        raise SafePruneError(
            f"External command failed with exit code {completed.returncode}: {joined}\n{stderr}"
        )

    return parse_null_separated_paths(completed.stdout, root)


def deduplicate_paths(paths: Iterable[Path]) -> list[Path]:
    """Deduplicate paths while preserving stable sorted output."""
    unique: dict[str, Path] = {}
    for path in paths:
        resolved = path.resolve(strict=False)
        unique[path_sort_key(resolved)] = resolved
    return [unique[key] for key in sorted(unique)]


def filter_paths_by_depth(paths: Iterable[Path], root: Path, min_depth: Optional[int], max_depth: Optional[int]) -> list[Path]:
    """Apply min/max depth filters consistently across fd and rg results."""
    filtered: list[Path] = []

    for path in paths:
        depth = relative_depth(path, root)
        if min_depth is not None and depth < min_depth:
            continue
        if max_depth is not None and depth > max_depth:
            continue
        filtered.append(path)

    return filtered


def apply_limit(paths: Sequence[Path], limit: Optional[int]) -> list[Path]:
    """Apply an optional result limit."""
    if limit is None:
        return list(paths)
    if limit < 1:
        raise SafePruneError("--limit must be greater than zero.")
    return list(paths[:limit])


def build_fd_base_command(fd_executable: str, fd_args: argparse.Namespace) -> list[str]:
    """Build common fd command arguments."""
    command = [
        fd_executable,
        "--color=never",
        "--print0",
    ]

    entry_type = getattr(fd_args, "entry_type", "file")
    if entry_type == "file":
        command.extend(["--type", "file"])
    elif entry_type == "folder":
        command.extend(["--type", "directory"])
    elif entry_type == "any":
        pass
    else:
        raise SafePruneError(f"Unsupported entry type: {entry_type}")

    if getattr(fd_args, "include_hidden", False):
        command.append("--hidden")

    if getattr(fd_args, "no_ignore", True):
        command.append("--no-ignore")

    if getattr(fd_args, "ignore_case", False):
        command.append("--ignore-case")

    if getattr(fd_args, "follow_links", False):
        command.append("--follow")

    max_depth = getattr(fd_args, "max_depth", None)
    if max_depth is not None:
        command.extend(["--max-depth", str(max_depth)])

    min_depth = getattr(fd_args, "min_depth", None)
    if min_depth is not None:
        command.extend(["--min-depth", str(min_depth)])

    for extension in normalize_extensions(getattr(fd_args, "extension", None)):
        command.extend(["--extension", extension])

    for exclude in getattr(fd_args, "exclude", []) or []:
        command.extend(["--exclude", exclude])

    return command


def collect_fd_targets(fd_args: argparse.Namespace, op_args: argparse.Namespace, tool_config: ToolConfig) -> list[Path]:
    """Collect fd path matches."""
    root = resolve_root(op_args.root)
    fd_executable = ensure_tool_available(tool_config.fd_executable, "fd or fdfind")
    base_command = build_fd_base_command(fd_executable, fd_args)
    glob_patterns = getattr(fd_args, "glob_pattern", None) or []

    all_paths: list[Path] = []

    if glob_patterns:
        for glob_pattern in glob_patterns:
            command = [*base_command, "--glob", "--", glob_pattern, "."]
            all_paths.extend(run_external_command(command, root))
    else:
        command = [*base_command, "--", ".", "."]
        all_paths.extend(run_external_command(command, root))

    all_paths = deduplicate_paths(all_paths)
    all_paths = filter_paths_by_depth(
        all_paths,
        root,
        getattr(fd_args, "min_depth", None),
        getattr(fd_args, "max_depth", None),
    )
    return all_paths


def build_rg_base_command(rg_executable: str, rg_args: argparse.Namespace) -> list[str]:
    """Build common rg command arguments."""
    command = [
        rg_executable,
        "--files-with-matches",
        "--null",
        "--color=never",
    ]

    if getattr(rg_args, "fixed_strings", False):
        command.append("--fixed-strings")

    if getattr(rg_args, "ignore_case", False):
        command.append("--ignore-case")

    if getattr(rg_args, "include_hidden", False):
        command.append("--hidden")

    if getattr(rg_args, "no_ignore", True):
        command.append("--no-ignore")

    if getattr(rg_args, "follow_links", False):
        command.append("--follow")

    max_depth = getattr(rg_args, "max_depth", None)
    if max_depth is not None:
        command.extend(["--max-depth", str(max_depth)])

    for extension in normalize_extensions(getattr(rg_args, "extension", None)):
        command.extend(["--glob", f"*.{extension}"])

    for glob_pattern in getattr(rg_args, "glob_pattern", []) or []:
        command.extend(["--glob", glob_pattern])

    for exclude in getattr(rg_args, "exclude", []) or []:
        command.extend(["--glob", f"!{exclude}"])

    return command


def collect_rg_targets(rg_args: argparse.Namespace, op_args: argparse.Namespace, tool_config: ToolConfig) -> list[Path]:
    """Collect rg content matches."""
    root = resolve_root(op_args.root)
    rg_executable = ensure_tool_available(tool_config.rg_executable, "rg")
    content_patterns = getattr(rg_args, "content_pattern", None) or []

    if not content_patterns:
        raise SafePruneError("The rg subcommand requires --content-pattern / -p.")

    match_mode = getattr(rg_args, "match_mode", "all")
    base_command = build_rg_base_command(rg_executable, rg_args)

    if match_mode == "any":
        command = [*base_command]
        for content_pattern in content_patterns:
            command.extend(["--regexp", content_pattern])
        command.append(".")
        paths = run_external_command(command, root)
    elif match_mode == "all":
        matching_sets: list[set[str]] = []
        path_by_key: dict[str, Path] = {}

        for content_pattern in content_patterns:
            command = [*base_command, "--regexp", content_pattern, "."]
            matches = run_external_command(command, root)
            keys = set()
            for path in matches:
                key = path_sort_key(path)
                keys.add(key)
                path_by_key[key] = path
            matching_sets.append(keys)

        if not matching_sets:
            paths = []
        else:
            common_keys = set.intersection(*matching_sets)
            paths = [path_by_key[key] for key in sorted(common_keys)]
    else:
        raise SafePruneError(f"Unsupported match mode: {match_mode}")

    paths = deduplicate_paths(paths)
    paths = filter_paths_by_depth(
        paths,
        root,
        getattr(rg_args, "min_depth", None),
        getattr(rg_args, "max_depth", None),
    )
    return paths


def path_is_under_directory(path: Path, directory: Path) -> bool:
    """Return True when path is inside directory or equal to directory."""
    try:
        path.resolve(strict=False).relative_to(directory.resolve(strict=False))
        return True
    except ValueError:
        return False


def rg_file_matches_fd_context(rg_file: Path, fd_contexts: Sequence[Path]) -> bool:
    """Return True when an rg file is allowed by fd file/folder contexts."""
    rg_key = path_sort_key(rg_file)

    for context in fd_contexts:
        if context.is_dir():
            if path_is_under_directory(rg_file, context):
                return True
        elif path_sort_key(context) == rg_key:
            return True

    return False


def collect_combined_targets(parsed: ParsedCli, tool_config: ToolConfig) -> tuple[list[Path], FilterTrace]:
    """Collect targets for fd+rg or rg+fd combined modes."""
    if parsed.fd is None or parsed.rg is None:
        raise SafePruneError("Combined mode requires both fd and rg arguments.")

    fd_candidates = collect_fd_targets(parsed.fd, parsed.operation, tool_config)
    rg_candidates = collect_rg_targets(parsed.rg, parsed.operation, tool_config)

    final_targets = [
        rg_file
        for rg_file in rg_candidates
        if rg_file_matches_fd_context(rg_file, fd_candidates)
    ]
    final_targets = deduplicate_paths(final_targets)

    final_keys = {path_sort_key(path) for path in final_targets}
    fd_file_candidates = [path for path in fd_candidates if path.is_file() or path.is_symlink()]

    filtered_by_rg = [
        path
        for path in fd_file_candidates
        if path_sort_key(path) not in final_keys
    ]
    filtered_by_fd = [
        path
        for path in rg_candidates
        if path_sort_key(path) not in final_keys
    ]

    trace = FilterTrace(
        order=parsed.order,
        fd_candidates=deduplicate_paths(fd_candidates),
        rg_candidates=deduplicate_paths(rg_candidates),
        filtered_by_fd=deduplicate_paths(filtered_by_fd),
        filtered_by_rg=deduplicate_paths(filtered_by_rg),
    )

    return final_targets, trace


def has_positive_fd_filter(fd_args: argparse.Namespace) -> bool:
    """Return True when fd deletion is constrained by a meaningful positive filter."""
    return bool(
        getattr(fd_args, "glob_pattern", None)
        or getattr(fd_args, "extension", None)
        or getattr(fd_args, "min_depth", None) is not None
        or getattr(fd_args, "max_depth", None) is not None
    )


def confirm_delete_if_needed(args: argparse.Namespace, count: int) -> None:
    """Prompt for confirmation unless explicitly bypassed."""
    if not getattr(args, "delete", False):
        return

    if getattr(args, "yes", False):
        return

    print(f"About to affect {count} target(s).")
    print("Type DELETE to continue, or anything else to abort: ", end="", flush=True)
    response = sys.stdin.readline().strip()
    if response != "DELETE":
        raise SafePruneError("Aborted by user confirmation check.")


def unique_quarantine_destination(quarantine_root: Path, relative_path: Path) -> Path:
    """Return a non-conflicting destination inside the quarantine directory."""
    destination = quarantine_root / relative_path
    if not destination.exists():
        return destination

    stem = destination.stem
    suffix = destination.suffix
    parent = destination.parent

    for index in range(1, 100000):
        candidate = parent / f"{stem}.{index}{suffix}"
        if not candidate.exists():
            return candidate

    raise SafePruneError(f"Unable to create unique quarantine path for: {destination}")


def move_to_quarantine(target: Path, root: Path, quarantine_dir: Path) -> Path:
    """Move a target into a quarantine directory, preserving relative structure."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    quarantine_root = quarantine_dir.expanduser().resolve(strict=False) / timestamp
    relative = target.resolve(strict=False).relative_to(root.resolve(strict=False))
    destination = unique_quarantine_destination(quarantine_root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(target), str(destination))
    return destination


def remove_target(target: Path, args: argparse.Namespace) -> None:
    """Remove a file or directory target."""
    if not target.exists() and not target.is_symlink():
        raise SafePruneError(f"Target no longer exists: {target}")

    is_junction = False
    is_junction_method = getattr(target, "is_junction", None)
    if callable(is_junction_method):
        is_junction = bool(is_junction_method())

    if target.is_symlink():
        try:
            target.unlink()
            return
        except OSError:
            target.rmdir()
            return

    if is_junction:
        target.rmdir()
        return

    if target.is_file():
        target.unlink()
        return

    if target.is_dir():
        if getattr(args, "recursive", False):
            shutil.rmtree(target)
        else:
            target.rmdir()
        return

    raise SafePruneError(f"Unsupported filesystem entry type: {target}")


def apply_targets(
    targets: Sequence[Path],
    root: Path,
    args: argparse.Namespace,
    command_name: str,
    trace: Optional[FilterTrace] = None,
) -> OperationStats:
    """Dry-run, delete, or quarantine matched targets."""
    stats = OperationStats(
        command=command_name,
        dry_run=not getattr(args, "delete", False),
        root=root,
        matched_count=len(targets),
        targets=list(targets),
        trace=trace,
    )

    quarantine_value = getattr(args, "quarantine_dir", None)
    quarantine_dir = Path(quarantine_value).expanduser() if quarantine_value else None

    if getattr(args, "delete", False) and len(targets) > 0:
        confirm_delete_if_needed(args, len(targets))

    for target in targets:
        resolved = target.resolve(strict=False)

        if resolved == root.resolve(strict=False):
            message = f"Refusing to affect root path itself: {resolved}"
            stats.skipped.append(message)
            stats.skipped_count += 1
            continue

        if not is_path_inside_root(resolved, root):
            message = f"Refusing path outside root: {resolved}"
            stats.skipped.append(message)
            stats.skipped_count += 1
            continue

        if not getattr(args, "delete", False):
            stats.would_be_affected.append(resolved)
            stats.would_be_affected_count += 1
            continue

        try:
            if quarantine_dir:
                move_to_quarantine(resolved, root, quarantine_dir)
            else:
                remove_target(resolved, args)
            stats.affected.append(resolved)
            stats.affected_count += 1
        except Exception as exc:
            stats.failures.append(f"{resolved}: {exc}")
            stats.failed_count += 1

    return stats


def print_path_list(title: str, paths: Sequence[Path], args: argparse.Namespace, color: str) -> None:
    """Print a labeled path list for verbose output."""
    print(colorize(f"{title}: {len(paths)}", color, args))
    for path in paths:
        print(f"  {path}")


def print_trace(trace: FilterTrace, args: argparse.Namespace) -> None:
    """Print verbose combined-mode filter trace."""
    order_text = " ".join(trace.order)
    print(colorize(f"Verbose filter trace ({order_text})", Ansi.CYAN, args))
    print_path_list("FD candidates/files/folders", trace.fd_candidates, args, Ansi.CYAN)
    print_path_list("RG candidates/files", trace.rg_candidates, args, Ansi.CYAN)
    print_path_list("Filtered by FD", trace.filtered_by_fd, args, Ansi.YELLOW)
    print_path_list("Filtered by RG", trace.filtered_by_rg, args, Ansi.YELLOW)


def print_stats_text(stats: OperationStats, args: argparse.Namespace) -> None:
    """Print a human-readable summary."""
    quiet = getattr(args, "quiet", False)
    verbose = getattr(args, "verbose", False)
    quarantine_dir = getattr(args, "quarantine_dir", None)

    if quiet:
        if stats.failed_count:
            print(f"failed={stats.failed_count}", file=sys.stderr)
        return

    if stats.trace is not None and verbose:
        print_trace(stats.trace, args)

    if stats.dry_run:
        print(colorize(f"Command: {stats.command}", Ansi.CYAN, args))
        print(colorize("Mode: dry-run", Ansi.YELLOW, args))
    elif quarantine_dir:
        print(colorize(f"Command: {stats.command}", Ansi.CYAN, args))
        print(colorize("Mode: quarantine", Ansi.MAGENTA, args))
    else:
        print(colorize(f"Command: {stats.command}", Ansi.CYAN, args))
        print(colorize("Mode: delete", Ansi.RED, args))

    print(f"Root: {stats.root}")
    print(f"Matched: {stats.matched_count}")

    if stats.dry_run:
        for target in stats.would_be_affected:
            print(f"{colorize('DRY-RUN:', Ansi.YELLOW, args)} {target}")
    elif quarantine_dir:
        for target in stats.affected:
            print(f"{colorize('QUARANTINE:', Ansi.MAGENTA, args)} {target}")
    else:
        for target in stats.affected:
            print(f"{colorize('DELETE:', Ansi.RED, args)} {target}")

    if verbose and stats.skipped:
        for skipped in stats.skipped:
            print(f"{colorize('SKIP:', Ansi.DIM, args)} {skipped}")

    if stats.failures:
        for failure in stats.failures:
            print(f"{colorize('FAIL:', Ansi.RED, args)} {failure}", file=sys.stderr)

    if stats.dry_run:
        print(colorize(f"Would be affected: {stats.would_be_affected_count}", Ansi.YELLOW, args))
    else:
        print(colorize(f"Affected: {stats.affected_count}", Ansi.RED if not quarantine_dir else Ansi.MAGENTA, args))
    print(f"Skipped: {stats.skipped_count}")
    print(f"Failed: {stats.failed_count}")


def print_stats_json(stats: OperationStats) -> None:
    """Print a machine-readable summary."""
    payload = {
        "command": stats.command,
        "dry_run": stats.dry_run,
        "root": str(stats.root),
        "matched_count": stats.matched_count,
        "would_be_affected_count": stats.would_be_affected_count,
        "affected_count": stats.affected_count,
        "skipped_count": stats.skipped_count,
        "failed_count": stats.failed_count,
        "targets": [str(path) for path in stats.targets],
        "would_be_affected": [str(path) for path in stats.would_be_affected],
        "affected": [str(path) for path in stats.affected],
        "skipped": stats.skipped,
        "failures": stats.failures,
        "trace": None,
    }

    if stats.trace is not None:
        payload["trace"] = {
            "order": list(stats.trace.order),
            "fd_candidates": [str(path) for path in stats.trace.fd_candidates],
            "rg_candidates": [str(path) for path in stats.trace.rg_candidates],
            "filtered_by_fd": [str(path) for path in stats.trace.filtered_by_fd],
            "filtered_by_rg": [str(path) for path in stats.trace.filtered_by_rg],
        }

    print(json.dumps(payload, indent=4, sort_keys=True))


def print_stats(stats: OperationStats, args: argparse.Namespace) -> None:
    """Print output in the requested format."""
    if getattr(args, "json", False):
        print_stats_json(stats)
    else:
        print_stats_text(stats, args)


def add_help_argument(parser: argparse.ArgumentParser) -> None:
    """Add standard help options, including -?."""
    parser.add_argument(
        "-h",
        "-?",
        "--help",
        action="help",
        help="Show this help menu and exit.",
    )


def add_operation_arguments(parser: argparse.ArgumentParser, suppress_defaults: bool = True) -> None:
    """Add common operation and safety arguments."""
    default = argparse.SUPPRESS if suppress_defaults else None

    parser.add_argument(
        "-r",
        "--root",
        default=default,
        help="Root directory to search. Defaults to the current directory.",
    )
    parser.add_argument(
        "-D",
        "--delete",
        action="store_true",
        default=default,
        help="Actually apply the operation. Without this flag, the command is a dry-run.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        default=default,
        help="Skip the interactive DELETE confirmation when --delete is used.",
    )
    parser.add_argument(
        "-Q",
        "--quarantine-dir",
        default=default,
        help="Move matched targets into this quarantine directory instead of permanently deleting them.",
    )
    parser.add_argument(
        "-R",
        "--recursive",
        action="store_true",
        default=default,
        help="Allow permanent deletion of non-empty directories. Not needed for files.",
    )
    parser.add_argument(
        "-A",
        "--allow-all",
        action="store_true",
        default=default,
        help="Allow delete/apply when no positive fd filter is provided.",
    )
    parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=default,
        help="Maximum number of final matched targets to affect or show.",
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        default=default,
        help="Print JSON output instead of text output.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=default,
        help="Suppress normal text output. Errors still go to stderr.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=default,
        help="Print additional skip/failure details and combined fd/rg filter traces.",
    )
    parser.add_argument(
        "-c",
        "--color",
        choices=("auto", "always", "never"),
        default=default,
        help="Color output mode. Use auto, always, or never. Defaults to auto.",
    )


def add_fd_arguments(parser: argparse.ArgumentParser, suppress_defaults: bool = True) -> None:
    """Add fd/path-style filtering arguments."""
    default = argparse.SUPPRESS if suppress_defaults else None

    parser.add_argument(
        "-t",
        "--entry-type",
        choices=("file", "folder", "any"),
        default=default,
        help=(
            "Filesystem entry type to match. Defaults to file. In combined fd+rg modes, "
            "folder matches restrict rg to files under those folders; folders are not deleted by rg."
        ),
    )
    parser.add_argument(
        "-g",
        "--glob-pattern",
        action="append",
        default=default,
        help="FD glob pattern to match path names. Glob matching is the default. Can be repeated.",
    )
    parser.add_argument(
        "-e",
        "--extension",
        action="append",
        default=default,
        help="FD extension filter, with or without a leading dot. Can be repeated.",
    )
    parser.add_argument(
        "-x",
        "--exclude",
        action="append",
        default=default,
        help="FD glob pattern to exclude. Can be repeated.",
    )
    parser.add_argument(
        "-m",
        "--max-depth",
        type=int,
        default=default,
        help="FD maximum search depth where a top-level child has depth 1.",
    )
    parser.add_argument(
        "-M",
        "--min-depth",
        type=int,
        default=default,
        help="FD minimum search depth where a top-level child has depth 1.",
    )
    parser.add_argument(
        "-a",
        "--include-hidden",
        action="store_true",
        default=default,
        help="FD include hidden files and directories.",
    )
    parser.add_argument(
        "-I",
        "--no-ignore",
        action="store_true",
        dest="no_ignore",
        default=default,
        help="FD ignore .gitignore/.ignore rules. This is enabled by default.",
    )
    parser.add_argument(
        "-G",
        "--respect-ignore",
        action="store_false",
        dest="no_ignore",
        default=default,
        help="FD respect .gitignore/.ignore rules. This disables the default --no-ignore behavior.",
    )
    parser.add_argument(
        "-i",
        "--ignore-case",
        action="store_true",
        default=default,
        help="FD use case-insensitive path matching.",
    )
    parser.add_argument(
        "-L",
        "--follow-links",
        action="store_true",
        default=default,
        help="FD follow symbolic links while searching.",
    )


def add_rg_arguments(parser: argparse.ArgumentParser, suppress_defaults: bool = True) -> None:
    """Add rg/content-style filtering arguments."""
    default = argparse.SUPPRESS if suppress_defaults else None

    parser.add_argument(
        "-p",
        "--content-pattern",
        action="append",
        default=default,
        help="RG content pattern to match. Can be repeated.",
    )
    parser.add_argument(
        "-P",
        "--match-mode",
        choices=("all", "any"),
        default=default,
        help="When multiple RG content patterns are provided, require all or any. Defaults to all.",
    )
    parser.add_argument(
        "-F",
        "--fixed-strings",
        action="store_true",
        default=default,
        help="RG treat content patterns as literal strings instead of regexes.",
    )
    parser.add_argument(
        "-g",
        "--glob-pattern",
        action="append",
        default=default,
        help="RG file glob filter. Can be repeated.",
    )
    parser.add_argument(
        "-e",
        "--extension",
        action="append",
        default=default,
        help="RG file extension filter, with or without a leading dot. Can be repeated.",
    )
    parser.add_argument(
        "-x",
        "--exclude",
        action="append",
        default=default,
        help="RG glob pattern to exclude. Can be repeated.",
    )
    parser.add_argument(
        "-m",
        "--max-depth",
        type=int,
        default=default,
        help="RG maximum search depth where a top-level child has depth 1.",
    )
    parser.add_argument(
        "-M",
        "--min-depth",
        type=int,
        default=default,
        help="RG minimum search depth where a top-level child has depth 1.",
    )
    parser.add_argument(
        "-a",
        "--include-hidden",
        action="store_true",
        default=default,
        help="RG include hidden files and directories.",
    )
    parser.add_argument(
        "-I",
        "--no-ignore",
        action="store_true",
        dest="no_ignore",
        default=default,
        help="RG ignore .gitignore/.ignore rules. This is enabled by default.",
    )
    parser.add_argument(
        "-G",
        "--respect-ignore",
        action="store_false",
        dest="no_ignore",
        default=default,
        help="RG respect .gitignore/.ignore rules. This disables the default --no-ignore behavior.",
    )
    parser.add_argument(
        "-i",
        "--ignore-case",
        action="store_true",
        default=default,
        help="RG use case-insensitive content/path matching.",
    )
    parser.add_argument(
        "-L",
        "--follow-links",
        action="store_true",
        default=default,
        help="RG follow symbolic links while searching.",
    )


def build_operation_parser(prog: str) -> argparse.ArgumentParser:
    """Build a parser for operation-level arguments."""
    parser = argparse.ArgumentParser(prog=prog, add_help=False)
    add_operation_arguments(parser, suppress_defaults=True)
    return parser


def build_main_parser() -> argparse.ArgumentParser:
    """Build the top-level help parser."""
    parser = argparse.ArgumentParser(
        prog=PROGRAM_NAME,
        description="Safely prune files/folders using fd path filters, rg content filters, or both.",
        add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Subcommands:\n"
            "  fd                 Match files/folders by path/name using fd.\n"
            "  rg                 Match files by content using rg.\n"
            "  fd ... rg ...      Run fd first, then narrow with rg content matches.\n"
            "  rg ... fd ...      Run rg first, then narrow with fd path/folder matches.\n\n"
            "Order matters in combined mode: the first subcommand defines the first candidate set,\n"
            "and verbose mode shows what the later filter removed. Combined modes affect files\n"
            "because rg returns files. FD folder matches restrict the file set to files under\n"
            "those folders.\n\n"
            "Examples:\n"
            "  filter-prune.py fd -g \"*preview*\"\n"
            "  filter-prune.py rg -p \"needle\" -e txt\n"
            "  filter-prune.py fd -g \"*preview*\" -e mp4 rg -p \"needle\"\n"
            "  filter-prune.py rg -p \"needle\" fd -g \"*preview*\" -e mp4\n"
        ),
    )
    add_help_argument(parser)
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"{PROGRAM_NAME} {VERSION}",
        help="Print version information and exit.",
    )
    add_operation_arguments(parser, suppress_defaults=False)
    return parser


def build_fd_parser(prog: str = f"{PROGRAM_NAME} fd") -> argparse.ArgumentParser:
    """Build the fd subcommand parser."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Find files/folders by path/name using fd, then dry-run, quarantine, or delete them.",
        add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "FD uses glob matching by default for --glob-pattern / -g.\n"
            "--no-ignore / -I is enabled by default; use --respect-ignore / -G to respect ignore files.\n\n"
            "Combined mode:\n"
            "  filter-prune.py fd [fd-options] rg [rg-options]\n"
            "Order matters: fd builds the first candidate set, then rg filters by content.\n"
        ),
    )
    add_help_argument(parser)
    add_operation_arguments(parser, suppress_defaults=True)
    add_fd_arguments(parser, suppress_defaults=True)
    return parser


def build_rg_parser(prog: str = f"{PROGRAM_NAME} rg") -> argparse.ArgumentParser:
    """Build the rg subcommand parser."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Find files by content using rg, then dry-run, quarantine, or delete them.",
        add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "RG always returns files. Use --content-pattern / -p for content filters.\n"
            "--no-ignore / -I is enabled by default; use --respect-ignore / -G to respect ignore files.\n\n"
            "Combined mode:\n"
            "  filter-prune.py rg [rg-options] fd [fd-options]\n"
            "Order matters: rg builds the first candidate set, then fd filters by path/folder.\n"
        ),
    )
    add_help_argument(parser)
    add_operation_arguments(parser, suppress_defaults=True)
    add_rg_arguments(parser, suppress_defaults=True)
    return parser


def print_combo_help(order: tuple[str, str]) -> None:
    """Print a unique help menu for an exact two-subcommand combination."""
    first, second = order
    first_description = "FD path/folder candidate set" if first == "fd" else "RG content candidate set"
    second_description = "FD path/folder filter" if second == "fd" else "RG content filter"

    print(
        f"usage: {PROGRAM_NAME} [global-options] {first} [{first}-options] {second} [{second}-options]\n"
    )
    print(f"Combined mode: {first} {second}")
    print()
    print("Order matters:")
    print(f"  1. {first} builds the first candidate set ({first_description}).")
    print(f"  2. {second} narrows that set ({second_description}).")
    print("  3. Verbose mode shows which targets each filter removed.")
    print()
    print("Combined modes affect files because rg returns files.")
    print("FD folder matches restrict the candidate set to files under those folders.")
    print()
    print("Global options can appear before, between, or after subcommands:")
    print("  -r, --root ROOT")
    print("  -D, --delete")
    print("  -y, --yes")
    print("  -Q, --quarantine-dir DIR")
    print("  -R, --recursive")
    print("  -A, --allow-all")
    print("  -l, --limit COUNT")
    print("  -j, --json")
    print("  -q, --quiet")
    print("  -v, --verbose")
    print("  -c, --color {auto,always,never}")
    print("  -h, -?, --help")
    print()
    print(f"{first.upper()} options are shown with:")
    print(f"  {PROGRAM_NAME} {first} --help")
    print()
    print(f"{second.upper()} options are shown with:")
    print(f"  {PROGRAM_NAME} {second} --help")
    print()
    print("Examples:")
    if order == ("fd", "rg"):
        print(f"  {PROGRAM_NAME} fd -g \"*preview*\" -e mp4 rg -p \"needle\"")
        print(f"  {PROGRAM_NAME} -v fd -t folder -g \"*cache*\" rg -p \"TODO\"")
    else:
        print(f"  {PROGRAM_NAME} rg -p \"needle\" fd -g \"*preview*\" -e mp4")
        print(f"  {PROGRAM_NAME} -v rg -p \"TODO\" fd -t folder -g \"*cache*\"")


def split_subcommand_segments(argv: Sequence[str]) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """Split argv into global tokens and command-specific token segments."""
    command_positions = [(index, token) for index, token in enumerate(argv) if token in COMMAND_NAMES]

    if not command_positions:
        return list(argv), []

    if len(command_positions) > 2:
        raise SafePruneError("At most two subcommands are supported: fd, rg, fd rg, or rg fd.")

    command_sequence = [command for _, command in command_positions]
    if len(set(command_sequence)) != len(command_sequence):
        raise SafePruneError("Duplicate subcommands are not supported. Use fd, rg, fd rg, or rg fd.")

    global_tokens = list(argv[: command_positions[0][0]])
    segments: list[tuple[str, list[str]]] = []

    for position_index, (command_start, command_name) in enumerate(command_positions):
        next_start = command_positions[position_index + 1][0] if position_index + 1 < len(command_positions) else len(argv)
        segments.append((command_name, list(argv[command_start + 1 : next_start])))

    return global_tokens, segments


def parse_cli(argv: Optional[Sequence[str]] = None) -> ParsedCli:
    """Parse a composable fd/rg CLI."""
    raw_args = list(sys.argv[1:] if argv is None else argv)

    if not raw_args:
        build_main_parser().print_help()
        raise SystemExit(0)

    if any(token in VERSION_FLAGS for token in raw_args):
        print(f"{PROGRAM_NAME} {VERSION}")
        raise SystemExit(0)

    command_tokens = [token for token in raw_args if token in COMMAND_NAMES]
    help_requested = any(token in HELP_FLAGS for token in raw_args)

    if help_requested:
        if len(command_tokens) >= 2:
            print_combo_help((command_tokens[0], command_tokens[1]))
        elif len(command_tokens) == 1:
            if command_tokens[0] == "fd":
                build_fd_parser().print_help()
            else:
                build_rg_parser().print_help()
        else:
            build_main_parser().print_help()
        raise SystemExit(0)

    global_tokens, segments = split_subcommand_segments(raw_args)

    if not segments:
        raise SafePruneError("A subcommand is required. Use fd, rg, fd rg, or rg fd.")

    operation = default_operation_args()
    fd_args = default_fd_args() if any(command == "fd" for command, _ in segments) else None
    rg_args = default_rg_args() if any(command == "rg" for command, _ in segments) else None

    global_parser = build_operation_parser(PROGRAM_NAME)
    global_namespace = global_parser.parse_args(global_tokens)
    merge_namespace_values(operation, global_namespace, OPERATION_KEYS)

    order: list[str] = []

    for command, segment_tokens in segments:
        order.append(command)

        if command == "fd":
            parser = build_fd_parser(f"{PROGRAM_NAME} {' '.join(order)}")
            namespace = parser.parse_args(segment_tokens)
            merge_namespace_values(operation, namespace, OPERATION_KEYS)
            if fd_args is None:
                fd_args = default_fd_args()
            merge_namespace_values(fd_args, namespace, FD_KEYS)
        elif command == "rg":
            parser = build_rg_parser(f"{PROGRAM_NAME} {' '.join(order)}")
            namespace = parser.parse_args(segment_tokens)
            merge_namespace_values(operation, namespace, OPERATION_KEYS)
            if rg_args is None:
                rg_args = default_rg_args()
            merge_namespace_values(rg_args, namespace, RG_KEYS)
        else:
            raise SafePruneError(f"Unsupported subcommand: {command}")

    return ParsedCli(
        operation=operation,
        order=tuple(order),
        fd=fd_args,
        rg=rg_args,
    )


def validate_depth_pair(min_depth: Optional[int], max_depth: Optional[int], label: str) -> None:
    """Validate min/max depth combinations."""
    if min_depth is not None and min_depth < 0:
        raise SafePruneError(f"{label} --min-depth cannot be negative.")

    if max_depth is not None and max_depth < 0:
        raise SafePruneError(f"{label} --max-depth cannot be negative.")

    if min_depth is not None and max_depth is not None and min_depth > max_depth:
        raise SafePruneError(f"{label} --min-depth cannot be greater than --max-depth.")


def validate_args(parsed: ParsedCli) -> None:
    """Validate parsed arguments."""
    op_args = parsed.operation

    if getattr(op_args, "limit", None) is not None and op_args.limit < 1:
        raise SafePruneError("--limit must be greater than zero.")

    if getattr(op_args, "quiet", False) and getattr(op_args, "verbose", False):
        raise SafePruneError("--quiet and --verbose cannot be used together.")

    if parsed.fd is not None:
        validate_depth_pair(parsed.fd.min_depth, parsed.fd.max_depth, "FD")

    if parsed.rg is not None:
        validate_depth_pair(parsed.rg.min_depth, parsed.rg.max_depth, "RG")
        if not parsed.rg.content_pattern:
            raise SafePruneError("The rg subcommand requires --content-pattern / -p.")

    if not getattr(op_args, "delete", False):
        return

    if parsed.order == ("fd",) and parsed.fd is not None:
        if not has_positive_fd_filter(parsed.fd) and not getattr(op_args, "allow_all", False):
            raise SafePruneError(
                "Refusing to delete with fd because no positive fd filter was provided. "
                "Add --glob-pattern / -g, --extension / -e, depth bounds, or pass --allow-all / -A."
            )


def run(parsed: ParsedCli, tool_config: ToolConfig) -> OperationStats:
    """Run the selected subcommand sequence."""
    validate_args(parsed)
    root = resolve_root(parsed.operation.root)

    trace: Optional[FilterTrace] = None
    command_name = " ".join(parsed.order)

    if parsed.order == ("fd",):
        if parsed.fd is None:
            raise SafePruneError("fd arguments were not parsed.")
        targets = collect_fd_targets(parsed.fd, parsed.operation, tool_config)
    elif parsed.order == ("rg",):
        if parsed.rg is None:
            raise SafePruneError("rg arguments were not parsed.")
        targets = collect_rg_targets(parsed.rg, parsed.operation, tool_config)
    elif parsed.order in (("fd", "rg"), ("rg", "fd")):
        targets, trace = collect_combined_targets(parsed, tool_config)
    else:
        raise SafePruneError(f"Unsupported subcommand sequence: {command_name}")

    targets = apply_limit(deduplicate_paths(targets), parsed.operation.limit)
    return apply_targets(targets, root, parsed.operation, command_name, trace=trace)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Program entry point."""
    try:
        parsed = parse_cli(argv)
        tool_config = resolve_tool_config()
        stats = run(parsed, tool_config)
        print_stats(stats, parsed.operation)
        return 1 if stats.failed_count else 0
    except SystemExit as exc:
        return int(exc.code or 0)
    except SafePruneError as exc:
        print(f"{PROGRAM_NAME}: error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(f"{PROGRAM_NAME}: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
