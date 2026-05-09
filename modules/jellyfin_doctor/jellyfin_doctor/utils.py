"""Shared helpers for Jellyfin Doctor."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def timestamp() -> str:
    """Return the timestamp format used in backup and disabled-folder names."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def unique_path(path: Path) -> Path:
    """Return ``path`` or a suffixed variant that does not already exist."""
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.name}.{index}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find unique path for {path}")


def disabled_path(path: Path, stamp: str | None = None) -> Path:
    """Return a unique disabled path next to ``path``."""
    return unique_path(path.with_name(f"{path.name}.disabled.{stamp or timestamp()}"))


def ensure_dir(path: Path, *, dry_run: bool = False) -> None:
    """Create a directory unless this is a dry run."""
    if not dry_run:
        path.mkdir(parents=True, exist_ok=True)


def file_size(path: Path) -> int:
    """Return file size, treating missing files as zero."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def tree_size(path: Path) -> tuple[int, int]:
    """Return ``(bytes, files)`` for a file or directory."""
    if not path.exists():
        return 0, 0
    if path.is_file():
        return file_size(path), 1
    total = 0
    count = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += file_size(child)
            count += 1
    return total, count


def to_jsonable(value: Any) -> Any:
    """Convert common project values into JSON-serializable structures."""
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    return value


def emit_result(value: Any, *, json_output: bool = False) -> None:
    """Print a result as JSON or compact human-readable text."""
    if json_output:
        print(json.dumps(to_jsonable(value), indent=2, sort_keys=True))
        return
    if isinstance(value, dict):
        for key, item in value.items():
            print(f"{key}: {item}")
    else:
        print(value)


def eprint(message: str) -> None:
    """Print a message to stderr."""
    print(message, file=sys.stderr)

