"""Common CLI argument types and task resolution helpers."""

from __future__ import annotations

import argparse
import math
from pathlib import Path


def positive(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("Timeouts/budgets must be finite and positive")
    return result


def positive_int(value: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Context length must be a positive integer") from error
    if result <= 0:
        raise argparse.ArgumentTypeError("Context length must be a positive integer")
    return result


def ram_percent(value: str) -> float:
    try:
        result = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("RAM percentage must be a number from 0 (exclusive) to 100") from error
    if not math.isfinite(result) or not 0 < result <= 100:
        raise argparse.ArgumentTypeError("RAM percentage must be greater than 0 and at most 100")
    return result


def resolve_tasks(task_args: list[Path] | None) -> dict[str, Path]:
    """Resolve task paths or names into a dictionary of {task_id: Path}."""
    builtin_tasks_dir = Path(__file__).parent.parent / "tasks"
    if not task_args:
        task_dirs: dict[str, Path] = {}
        if builtin_tasks_dir.is_dir():
            for child in sorted(builtin_tasks_dir.iterdir()):
                if child.is_dir() and (child / "task.json").is_file():
                    task_dirs[child.name] = child
        if not task_dirs and (builtin_tasks_dir / "py-grep-smoke").is_dir():
            task_dirs["py-grep-smoke"] = builtin_tasks_dir / "py-grep-smoke"
        return task_dirs

    task_dirs = {}
    for item in task_args:
        p = Path(item)
        if not p.exists():
            candidate = builtin_tasks_dir / p
            if candidate.exists():
                p = candidate
        if not p.exists():
            raise FileNotFoundError(f"Task path {item} does not exist")
        if not (p / "task.json").is_file():
            raise ValueError(f"Task directory {p} does not contain task.json")
        task_dirs[p.name] = p
    return task_dirs
