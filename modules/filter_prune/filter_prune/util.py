"""Utility helpers for filter-prune."""

from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional, Sequence

from filter_prune.models import SafePruneError, TargetInfo, ToolConfig


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


def path_sort_key(path: Path) -> str:
    """Return a stable, case-insensitive path sort key."""
    return str(path).replace("\\", "/").lower()


def target_sort_key(target: TargetInfo) -> str:
    """Return a stable sort key for target info."""
    return path_sort_key(target.path)


def deduplicate_paths(paths: Iterable[Path]) -> list[Path]:
    """Deduplicate paths while preserving stable sorted output."""
    unique: dict[str, Path] = {}
    for path in paths:
        resolved = path.resolve(strict=False)
        unique[path_sort_key(resolved)] = resolved
    return [unique[key] for key in sorted(unique)]


def deduplicate_targets(targets: Iterable[TargetInfo]) -> list[TargetInfo]:
    """Deduplicate targets by absolute path."""
    unique: dict[str, TargetInfo] = {}
    for target in targets:
        key = path_sort_key(target.path.resolve(strict=False))
        if key not in unique:
            unique[key] = TargetInfo(
                path=target.path.resolve(strict=False),
                root=target.root.resolve(strict=False),
            )
    return [unique[key] for key in sorted(unique)]


def resolve_roots(root_values: Sequence[str]) -> list[Path]:
    """Resolve one or more search roots."""
    values = list(root_values) if root_values else ["."]
    roots: list[Path] = []

    for root_value in values:
        root = Path(root_value).expanduser()
        if not root.exists():
            raise SafePruneError(f"Root path does not exist: {root}")
        if not root.is_dir():
            raise SafePruneError(f"Root path is not a directory: {root}")
        roots.append(root.resolve())

    return deduplicate_paths(roots)


def is_path_inside_root(path: Path, root: Path) -> bool:
    """Return True when path is root or a descendant of root."""
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def path_is_under_directory(path: Path, directory: Path) -> bool:
    """Return True when path is inside directory or equal to directory."""
    try:
        path.resolve(strict=False).relative_to(directory.resolve(strict=False))
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


def parse_null_separated_targets(stdout: bytes, root: Path) -> list[TargetInfo]:
    """Parse NUL-separated command output into resolved targets."""
    targets: list[TargetInfo] = []
    for raw_part in stdout.split(b"\0"):
        if not raw_part:
            continue
        raw_text = raw_part.decode("utf-8", errors="replace")
        raw_path = Path(raw_text)
        path = raw_path if raw_path.is_absolute() else root / raw_path
        resolved = path.resolve(strict=False)
        if is_path_inside_root(resolved, root):
            targets.append(TargetInfo(path=resolved, root=root))
    return targets


def run_external_command(command: Sequence[str], root: Path) -> list[TargetInfo]:
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

    return parse_null_separated_targets(completed.stdout, root)


def target_kind(path: Path) -> str:
    """Return a broad target kind for summary and operation behavior."""
    if path.is_symlink():
        return "other"
    if path.is_file():
        return "file"
    if path.is_dir():
        return "folder"
    return "other"


def extension_key(path: Path) -> str:
    """Return a normalized extension key for summary output."""
    suffix = path.suffix.lower()
    if suffix:
        return suffix
    return "[no-extension]"


def safe_file_size(path: Path) -> int:
    """Return file size, or zero if unavailable."""
    try:
        if path.is_symlink():
            return path.lstat().st_size
        return path.stat().st_size
    except OSError:
        return 0


def safe_directory_size(path: Path) -> int:
    """Return recursive folder size without following directory symlinks."""
    total = 0

    try:
        if path.is_symlink():
            return path.lstat().st_size
    except OSError:
        return 0

    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if not (Path(dirpath) / dirname).is_symlink()
        ]

        for filename in filenames:
            file_path = Path(dirpath) / filename
            total += safe_file_size(file_path)

    return total


def format_bytes(byte_count: int) -> str:
    """Format bytes using binary units."""
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    value = float(byte_count)

    for unit in units:
        if abs(value) < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.2f} {unit}"
        value /= 1024.0

    return f"{byte_count} B"


def safe_root_label(root: Path) -> str:
    """Return a stable filesystem-safe label for preserving multi-root moves."""
    resolved = root.resolve(strict=False)
    base = resolved.name or resolved.drive or "root"
    digest = hashlib.sha1(str(resolved).encode("utf-8", errors="replace")).hexdigest()[:8]
    cleaned = "".join(char if char.isalnum() or char in ("-", "_", ".") else "_" for char in base)
    cleaned = cleaned.strip("._") or "root"
    return f"{cleaned}-{digest}"


def unique_destination(destination: Path) -> Path:
    """Return a non-conflicting destination path."""
    if not destination.exists():
        return destination

    stem = destination.stem
    suffix = destination.suffix
    parent = destination.parent

    for index in range(1, 100000):
        candidate = parent / f"{stem}.{index}{suffix}"
        if not candidate.exists():
            return candidate

    raise SafePruneError(f"Unable to create unique destination path for: {destination}")


def render_template(template: str, target: TargetInfo, index: int) -> str:
    """Render operation templates using target metadata."""
    relative = target.path.resolve(strict=False).relative_to(target.root.resolve(strict=False))
    values = {
        "path": str(target.path),
        "root": str(target.root),
        "relative": str(relative),
        "kind": target_kind(target.path),
        "index": str(index),
    }
    return template.format(**values)


def quote_command_parts(parts: Sequence[str]) -> str:
    """Quote command parts for shell execution."""
    if os.name == "nt":
        return subprocess.list2cmdline(list(parts))
    return shlex.join(list(parts))


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
    from filter_prune.models import Ansi

    if not should_use_color(args):
        return text
    return f"{color}{text}{Ansi.RESET}"
