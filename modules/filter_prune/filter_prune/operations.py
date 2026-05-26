"""Operations applied to matched targets."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import FilterTrace, OperationStats, SafePruneError, TargetInfo, TargetSummary
from .util import (
    colorize,
    extension_key,
    format_bytes,
    is_path_inside_root,
    path_is_under_directory,
    relative_depth,
    render_template,
    safe_directory_size,
    safe_file_size,
    safe_root_label,
    target_kind,
    target_sort_key,
    unique_destination,
)


def summarize_targets(targets: list[TargetInfo]) -> TargetSummary:
    """Calculate counts and size summaries for target list."""
    extension_counts: Counter[str] = Counter()
    summary = TargetSummary(target_count=len(targets))

    for target in targets:
        kind = target_kind(target.path)

        if kind == "file":
            summary.file_count += 1
            summary.total_file_size_bytes += safe_file_size(target.path)
            extension_counts[extension_key(target.path)] += 1
        elif kind == "folder":
            summary.folder_count += 1
            summary.total_folder_size_bytes += safe_directory_size(target.path)
        else:
            summary.other_count += 1

    summary.file_extension_counts = dict(sorted(extension_counts.items()))
    return summary


def prune_nested_targets(targets: list[TargetInfo]) -> list[TargetInfo]:
    """Remove child targets when a parent folder is already targeted."""
    sorted_targets = sorted(
        targets,
        key=lambda target: (relative_depth(target.path, target.root), target_sort_key(target)),
    )

    kept: list[TargetInfo] = []
    kept_folders: list[Path] = []

    for target in sorted_targets:
        if any(path_is_under_directory(target.path, folder) and target.path != folder for folder in kept_folders):
            continue

        kept.append(target)

        if target_kind(target.path) == "folder":
            kept_folders.append(target.path.resolve(strict=False))

    return sorted(kept, key=target_sort_key)


def operation_confirmation_word(operation: str) -> str:
    """Return the confirmation word for an operation."""
    if operation == "delete":
        return "DELETE"
    if operation == "move":
        return "MOVE"
    if operation == "quarantine":
        return "QUARANTINE"
    if operation == "script":
        return "SCRIPT"
    if operation == "cat":
        return "CAT"
    return "EXECUTE"


def confirm_execute_if_needed(args: argparse.Namespace, count: int) -> None:
    """Prompt for confirmation unless explicitly bypassed."""
    if not getattr(args, "execute", False):
        return

    if getattr(args, "yes", False):
        return

    word = operation_confirmation_word(args.operation)
    print(f"About to {args.operation} {count} target(s).")
    print(f"Type {word} to continue, or anything else to abort: ", end="", flush=True)
    response = sys.stdin.readline().strip()
    if response != word:
        raise SafePruneError("Aborted by user confirmation check.")


def resolve_operation_target_dir(args: argparse.Namespace) -> Optional[Path]:
    """Return operation target directory for move/quarantine operations."""
    operation = getattr(args, "operation", "delete")

    if operation in ("delete", "script", "cat"):
        return None

    target_dir_value = getattr(args, "target_dir", None)

    if operation == "move":
        if not target_dir_value:
            raise SafePruneError("The move operation requires --target-dir / -T.")
        return Path(target_dir_value).expanduser().resolve(strict=False)

    if operation == "quarantine":
        if target_dir_value:
            return Path(target_dir_value).expanduser().resolve(strict=False)
        return (Path.cwd() / ".filter-prune-quarantine").resolve(strict=False)

    raise SafePruneError(f"Unsupported operation: {operation}")


def operation_destination(target: TargetInfo, args: argparse.Namespace) -> Optional[Path]:
    """Return destination path for move/quarantine operations."""
    target_dir = resolve_operation_target_dir(args)

    if target_dir is None:
        return None

    relative = target.path.resolve(strict=False).relative_to(target.root.resolve(strict=False))
    root_label = safe_root_label(target.root)

    if args.operation == "quarantine":
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return unique_destination(target_dir / timestamp / root_label / relative)

    return unique_destination(target_dir / root_label / relative)


def move_target(target: TargetInfo, args: argparse.Namespace) -> Path:
    """Move a target to the operation destination."""
    destination = operation_destination(target, args)
    if destination is None:
        raise SafePruneError("Move destination could not be resolved.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(target.path), str(destination))
    return destination


def remove_target(target: TargetInfo, args: argparse.Namespace) -> None:
    """Remove a file or directory target."""
    path = target.path

    if not path.exists() and not path.is_symlink():
        raise SafePruneError(f"Target no longer exists: {path}")

    is_junction = False
    is_junction_method = getattr(path, "is_junction", None)
    if callable(is_junction_method):
        is_junction = bool(is_junction_method())

    if path.is_symlink():
        try:
            path.unlink()
            return
        except OSError:
            path.rmdir()
            return

    if is_junction:
        path.rmdir()
        return

    if path.is_file():
        path.unlink()
        return

    if path.is_dir():
        if getattr(args, "recursive", False):
            shutil.rmtree(path)
        else:
            path.rmdir()
        return

    raise SafePruneError(f"Unsupported filesystem entry type: {path}")


def render_script_command(target: TargetInfo, args: argparse.Namespace, index: int) -> tuple[list[str], str]:
    """Render script command arguments and working directory."""
    script_command = getattr(args, "script_command", None)
    if not script_command:
        raise SafePruneError("The script operation requires --script-command / -S.")

    rendered_command = render_template(script_command, target, index)
    rendered_args = [
        render_template(script_arg, target, index)
        for script_arg in getattr(args, "script_arg", []) or []
    ]

    working_dir_template = getattr(args, "working_dir", None)
    if working_dir_template:
        working_dir = render_template(working_dir_template, target, index)
    else:
        working_dir = str(target.root)

    return [rendered_command, *rendered_args], working_dir


def run_script_target(target: TargetInfo, args: argparse.Namespace, index: int) -> None:
    """Run the configured script command for a single target."""
    command_parts, working_dir = render_script_command(target, args, index)

    if getattr(args, "shell", False):
        from filter_prune.util import quote_command_parts

        command = quote_command_parts(command_parts)
        completed = subprocess.run(
            command,
            cwd=working_dir,
            shell=True,
            check=False,
        )
    else:
        completed = subprocess.run(
            command_parts,
            cwd=working_dir,
            shell=False,
            check=False,
        )

    if completed.returncode != 0:
        raise SafePruneError(f"Script exited with code {completed.returncode}: {command_parts[0]}")


def looks_binary(data: bytes) -> bool:
    """Return True when a byte buffer appears to be binary."""
    return b"\0" in data


def print_file_contents(target: TargetInfo, args: argparse.Namespace) -> None:
    """Print file contents for cat operation."""
    path = target.path
    max_bytes = getattr(args, "max_bytes", None)
    encoding = getattr(args, "encoding", "utf-8")
    decode_errors = getattr(args, "decode_errors", "replace")
    no_headers = getattr(args, "no_headers", False)
    allow_binary = getattr(args, "allow_binary", False)

    if max_bytes is not None and max_bytes < 1:
        raise SafePruneError("--max-bytes must be greater than zero.")

    read_size = max_bytes if max_bytes is not None else None

    with path.open("rb") as file_handle:
        data = file_handle.read(read_size)

    if looks_binary(data) and not allow_binary:
        print(f"SKIP-BINARY: {path}", file=sys.stderr)
        return

    if not no_headers:
        print(f"===== FILE: {path} =====")

    text = data.decode(encoding, errors=decode_errors)
    print(text, end="" if text.endswith("\n") else "\n")


def print_folder_name(target: TargetInfo, args: argparse.Namespace) -> None:
    """Print folder path for cat operation."""
    no_headers = getattr(args, "no_headers", False)

    if no_headers:
        print(target.path)
    else:
        print(f"===== FOLDER: {target.path} =====")


def run_cat_target(target: TargetInfo, args: argparse.Namespace) -> None:
    """Run cat operation for a single target."""
    kind = target_kind(target.path)

    if kind == "file":
        print_file_contents(target, args)
    elif kind == "folder":
        print_folder_name(target, args)
    else:
        print(f"===== OTHER: {target.path} =====")


def execute_operation(target: TargetInfo, args: argparse.Namespace, index: int) -> None:
    """Execute the selected operation for one target."""
    if args.operation == "delete":
        remove_target(target, args)
    elif args.operation in ("move", "quarantine"):
        move_target(target, args)
    elif args.operation == "script":
        run_script_target(target, args, index)
    elif args.operation == "cat":
        run_cat_target(target, args)
    else:
        raise SafePruneError(f"Unsupported operation: {args.operation}")


def apply_targets(
    targets: list[TargetInfo],
    roots: list[Path],
    args: argparse.Namespace,
    command_name: str,
    trace: Optional[FilterTrace] = None,
) -> OperationStats:
    """Dry-run or execute the selected operation against matched targets."""
    pruned_targets = prune_nested_targets(targets)
    summary = summarize_targets(pruned_targets)

    stats = OperationStats(
        command=command_name,
        dry_run=not getattr(args, "execute", False),
        operation=getattr(args, "operation", "delete"),
        roots=list(roots),
        matched_count=len(pruned_targets),
        targets=list(pruned_targets),
        summary=summary,
        trace=trace,
    )

    operation_target_dir = resolve_operation_target_dir(args)

    if getattr(args, "execute", False) and len(pruned_targets) > 0:
        confirm_execute_if_needed(args, len(pruned_targets))

    for index, target in enumerate(pruned_targets, start=1):
        resolved = target.path.resolve(strict=False)

        if resolved in [root.resolve(strict=False) for root in roots]:
            message = f"Refusing to affect root path itself: {resolved}"
            stats.skipped.append(message)
            stats.skipped_count += 1
            continue

        if not any(is_path_inside_root(resolved, root) for root in roots):
            message = f"Refusing path outside configured roots: {resolved}"
            stats.skipped.append(message)
            stats.skipped_count += 1
            continue

        if operation_target_dir is not None and path_is_under_directory(resolved, operation_target_dir):
            message = f"Refusing to affect path inside operation target directory: {resolved}"
            stats.skipped.append(message)
            stats.skipped_count += 1
            continue

        if not getattr(args, "execute", False):
            stats.would_be_affected.append(target)
            stats.would_be_affected_count += 1
            continue

        try:
            execute_operation(target, args, index)
            stats.affected.append(target)
            stats.affected_count += 1
        except Exception as exc:
            stats.failures.append(f"{resolved}: {exc}")
            stats.failed_count += 1
            if getattr(args, "stop_on_error", False):
                break

    return stats


def operation_label(stats: OperationStats) -> str:
    """Return display label for current operation."""
    return stats.operation.upper()


def operation_color(stats: OperationStats) -> str:
    """Return display color for current operation."""
    from filter_prune.models import Ansi

    if stats.operation == "delete":
        return Ansi.RED
    if stats.operation == "move":
        return Ansi.GREEN
    if stats.operation == "quarantine":
        return Ansi.MAGENTA
    if stats.operation == "script":
        return Ansi.CYAN
    if stats.operation == "cat":
        return Ansi.CYAN
    return Ansi.CYAN


def print_target_list(title: str, targets: list[TargetInfo], args: argparse.Namespace, color: str) -> None:
    """Print a labeled target list for verbose output."""
    print(colorize(f"{title}: {len(targets)}", color, args))
    for target in targets:
        print(f"  {target.path}")


def print_trace(trace: FilterTrace, args: argparse.Namespace) -> None:
    """Print verbose combined-mode filter trace."""
    from filter_prune.models import Ansi

    order_text = " ".join(trace.order)
    print(colorize(f"Verbose filter trace ({order_text})", Ansi.CYAN, args))
    print_target_list("FD candidates/files/folders", trace.fd_candidates, args, Ansi.CYAN)
    print_target_list("RG candidates/files", trace.rg_candidates, args, Ansi.CYAN)
    print_target_list("Filtered by FD", trace.filtered_by_fd, args, Ansi.YELLOW)
    print_target_list("Filtered by RG", trace.filtered_by_rg, args, Ansi.YELLOW)


def print_summary(summary: TargetSummary) -> None:
    """Print file/folder/size summary."""
    print("Summary:")
    print(f"  Files: {summary.file_count}")
    print(f"  Folders: {summary.folder_count}")
    print(f"  Other: {summary.other_count}")

    if summary.file_extension_counts:
        print("  File extensions:")
        for extension, count in summary.file_extension_counts.items():
            print(f"    {extension}: {count}")
    else:
        print("  File extensions: none")

    print(f"  Total file size: {format_bytes(summary.total_file_size_bytes)} ({summary.total_file_size_bytes} bytes)")
    print(f"  Total folder size: {format_bytes(summary.total_folder_size_bytes)} ({summary.total_folder_size_bytes} bytes)")
    print(f"  Total combined size: {format_bytes(summary.total_size_bytes)} ({summary.total_size_bytes} bytes)")


def print_stats_text(stats: OperationStats, args: argparse.Namespace) -> None:
    """Print a human-readable summary."""
    from filter_prune.models import Ansi

    quiet = getattr(args, "quiet", False)
    verbose = getattr(args, "verbose", False)

    if quiet:
        if stats.failed_count:
            print(f"failed={stats.failed_count}", file=sys.stderr)
        return

    if stats.trace is not None and verbose:
        print_trace(stats.trace, args)

    operation_text = operation_label(stats)
    operation_text_colored = colorize(operation_text, operation_color(stats), args)

    print(colorize(f"Command: {stats.command}", Ansi.CYAN, args))
    print(colorize(f"Mode: {'dry-run' if stats.dry_run else 'execute'}", Ansi.YELLOW if stats.dry_run else operation_color(stats), args))
    print(f"Operation: {operation_text_colored}")

    print("Roots:")
    for root in stats.roots:
        print(f"  {root}")

    print(f"Matched: {stats.matched_count}")

    if stats.dry_run:
        for target in stats.would_be_affected:
            print(f"{colorize('DRY-RUN:', Ansi.YELLOW, args)} {target.path}")
    else:
        for target in stats.affected:
            print(f"{operation_text_colored}: {target.path}")

    if verbose and stats.skipped:
        for skipped in stats.skipped:
            print(f"{colorize('SKIP:', Ansi.DIM, args)} {skipped}")

    if stats.failures:
        for failure in stats.failures:
            print(f"{colorize('FAIL:', Ansi.RED, args)} {failure}", file=sys.stderr)

    print_summary(stats.summary)

    if stats.dry_run:
        print(colorize(f"Would be affected: {stats.would_be_affected_count}", Ansi.YELLOW, args))
    else:
        print(colorize(f"Affected: {stats.affected_count}", operation_color(stats), args))

    print(f"Skipped: {stats.skipped_count}")
    print(f"Failed: {stats.failed_count}")


def print_stats_json(stats: OperationStats) -> None:
    """Print a machine-readable summary."""
    import json

    payload = {
        "command": stats.command,
        "dry_run": stats.dry_run,
        "operation": stats.operation,
        "roots": [str(root) for root in stats.roots],
        "matched_count": stats.matched_count,
        "would_be_affected_count": stats.would_be_affected_count,
        "affected_count": stats.affected_count,
        "skipped_count": stats.skipped_count,
        "failed_count": stats.failed_count,
        "targets": [str(target.path) for target in stats.targets],
        "would_be_affected": [str(target.path) for target in stats.would_be_affected],
        "affected": [str(target.path) for target in stats.affected],
        "skipped": stats.skipped,
        "failures": stats.failures,
        "summary": {
            "target_count": stats.summary.target_count,
            "file_count": stats.summary.file_count,
            "folder_count": stats.summary.folder_count,
            "other_count": stats.summary.other_count,
            "file_extension_counts": stats.summary.file_extension_counts,
            "total_file_size_bytes": stats.summary.total_file_size_bytes,
            "total_folder_size_bytes": stats.summary.total_folder_size_bytes,
            "total_size_bytes": stats.summary.total_size_bytes,
        },
        "trace": None,
    }

    if stats.trace is not None:
        payload["trace"] = {
            "order": list(stats.trace.order),
            "fd_candidates": [str(target.path) for target in stats.trace.fd_candidates],
            "rg_candidates": [str(target.path) for target in stats.trace.rg_candidates],
            "filtered_by_fd": [str(target.path) for target in stats.trace.filtered_by_fd],
            "filtered_by_rg": [str(target.path) for target in stats.trace.filtered_by_rg],
        }

    print(json.dumps(payload, indent=4, sort_keys=True))


def print_stats(stats: OperationStats, args: argparse.Namespace) -> None:
    """Print output in the requested format."""
    if getattr(args, "json", False):
        print_stats_json(stats)
    else:
        print_stats_text(stats, args)
