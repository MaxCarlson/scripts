"""Search backends for fd, rg, and combined fd/rg filtering."""

from __future__ import annotations

import argparse
from typing import Optional

from filter_prune.models import FilterTrace, ParsedCli, SafePruneError, TargetInfo, ToolConfig
from filter_prune.util import (
    deduplicate_targets,
    ensure_tool_available,
    normalize_extensions,
    path_is_under_directory,
    path_sort_key,
    relative_depth,
    resolve_roots,
    run_external_command,
    target_kind,
)


def filter_targets_by_depth(
    targets: list[TargetInfo],
    min_depth: Optional[int],
    max_depth: Optional[int],
) -> list[TargetInfo]:
    """Apply min/max depth filters consistently across fd and rg results."""
    filtered: list[TargetInfo] = []

    for target in targets:
        depth = relative_depth(target.path, target.root)
        if min_depth is not None and depth < min_depth:
            continue
        if max_depth is not None and depth > max_depth:
            continue
        filtered.append(target)

    return filtered


def apply_limit(targets: list[TargetInfo], limit: Optional[int]) -> list[TargetInfo]:
    """Apply an optional result limit."""
    if limit is None:
        return list(targets)
    if limit < 1:
        raise SafePruneError("--limit must be greater than zero.")
    return list(targets[:limit])


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


def collect_fd_targets(fd_args: argparse.Namespace, op_args: argparse.Namespace, tool_config: ToolConfig) -> list[TargetInfo]:
    """Collect fd path matches across all roots."""
    roots = resolve_roots(op_args.roots)
    fd_executable = ensure_tool_available(tool_config.fd_executable, "fd or fdfind")
    all_targets: list[TargetInfo] = []

    for root in roots:
        base_command = build_fd_base_command(fd_executable, fd_args)
        glob_patterns = getattr(fd_args, "glob_pattern", None) or []

        if glob_patterns:
            for glob_pattern in glob_patterns:
                command = [*base_command, "--glob", "--", glob_pattern, "."]
                all_targets.extend(run_external_command(command, root))
        else:
            command = [*base_command, "--", ".", "."]
            all_targets.extend(run_external_command(command, root))

    all_targets = deduplicate_targets(all_targets)
    all_targets = filter_targets_by_depth(
        all_targets,
        getattr(fd_args, "min_depth", None),
        getattr(fd_args, "max_depth", None),
    )
    return all_targets


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


def collect_rg_targets(rg_args: argparse.Namespace, op_args: argparse.Namespace, tool_config: ToolConfig) -> list[TargetInfo]:
    """Collect rg content matches across all roots."""
    roots = resolve_roots(op_args.roots)
    rg_executable = ensure_tool_available(tool_config.rg_executable, "rg")
    content_patterns = getattr(rg_args, "content_pattern", None) or []

    if not content_patterns:
        raise SafePruneError("The rg subcommand requires --content-pattern / -p.")

    all_targets: list[TargetInfo] = []
    match_mode = getattr(rg_args, "match_mode", "all")

    for root in roots:
        base_command = build_rg_base_command(rg_executable, rg_args)

        if match_mode == "any":
            command = [*base_command]
            for content_pattern in content_patterns:
                command.extend(["--regexp", content_pattern])
            command.append(".")
            all_targets.extend(run_external_command(command, root))
        elif match_mode == "all":
            matching_sets: list[set[str]] = []
            target_by_key: dict[str, TargetInfo] = {}

            for content_pattern in content_patterns:
                command = [*base_command, "--regexp", content_pattern, "."]
                matches = run_external_command(command, root)
                keys = set()

                for target in matches:
                    key = path_sort_key(target.path)
                    keys.add(key)
                    target_by_key[key] = target

                matching_sets.append(keys)

            if matching_sets:
                common_keys = set.intersection(*matching_sets)
                all_targets.extend(target_by_key[key] for key in sorted(common_keys))
        else:
            raise SafePruneError(f"Unsupported match mode: {match_mode}")

    all_targets = deduplicate_targets(all_targets)
    all_targets = filter_targets_by_depth(
        all_targets,
        getattr(rg_args, "min_depth", None),
        getattr(rg_args, "max_depth", None),
    )
    return all_targets


def rg_file_matches_fd_context(rg_file: TargetInfo, fd_contexts: list[TargetInfo]) -> bool:
    """Return True when an rg file is allowed by fd file/folder contexts."""
    rg_key = path_sort_key(rg_file.path)

    for context in fd_contexts:
        if target_kind(context.path) == "folder":
            if path_is_under_directory(rg_file.path, context.path):
                return True
        elif path_sort_key(context.path) == rg_key:
            return True

    return False


def collect_combined_targets(parsed: ParsedCli, tool_config: ToolConfig) -> tuple[list[TargetInfo], FilterTrace]:
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
    final_targets = deduplicate_targets(final_targets)

    final_keys = {path_sort_key(target.path) for target in final_targets}
    fd_file_candidates = [
        target
        for target in fd_candidates
        if target_kind(target.path) == "file" or target.path.is_symlink()
    ]

    filtered_by_rg = [
        target
        for target in fd_file_candidates
        if path_sort_key(target.path) not in final_keys
    ]
    filtered_by_fd = [
        target
        for target in rg_candidates
        if path_sort_key(target.path) not in final_keys
    ]

    trace = FilterTrace(
        order=parsed.order,
        fd_candidates=deduplicate_targets(fd_candidates),
        rg_candidates=deduplicate_targets(rg_candidates),
        filtered_by_fd=deduplicate_targets(filtered_by_fd),
        filtered_by_rg=deduplicate_targets(filtered_by_rg),
    )

    return final_targets, trace
