"""
Persistence and file layout management for benchmark_core.

Manages the filesystem layout:
reports/
    <run_id>/
        run.json
        trials.jsonl
        summary.json
        summary.csv
        report.md
        evidence/
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional, Union

from .models import RunInfo, TrialResult


class BenchmarkStorageError(Exception):
    """Base exception for benchmark_core storage operations."""


class CorruptedDataError(BenchmarkStorageError, ValueError):
    """Raised when an authoritative file contains malformed data."""


class DuplicateTrialError(BenchmarkStorageError, ValueError):
    """Raised when attempting to append a trial with an already recorded trial_id."""


def save_run(run_dir: Union[Path, str], run_info: RunInfo, overwrite: bool = False) -> Path:
    """
    Save RunInfo to run.json within the target run directory.

    Args:
        run_dir: Destination directory for the benchmark run.
        run_info: The RunInfo batch configuration to save.
        overwrite: If False, raises FileExistsError if run.json already exists.

    Returns:
        Path to the written run.json file.
    """
    dir_path = Path(run_dir)
    dir_path.mkdir(parents=True, exist_ok=True)
    target_file = dir_path / "run.json"

    if target_file.exists() and not overwrite:
        raise FileExistsError(
            f"Authoritative run file already exists at {target_file}. "
            "Pass overwrite=True to explicitly replace it."
        )

    temp_file = dir_path / "run.json.tmp"
    try:
        temp_file.write_text(run_info.to_json() + "\n", encoding="utf-8")
        temp_file.replace(target_file)
    finally:
        if temp_file.exists():
            temp_file.unlink(missing_ok=True)

    return target_file


def load_run_info(run_file: Union[Path, str]) -> RunInfo:
    """Load and validate RunInfo from run.json."""
    p = Path(run_file)
    if p.is_dir():
        p = p / "run.json"
    if not p.is_file():
        raise FileNotFoundError(f"RunInfo file not found at {p}")

    try:
        content = p.read_text(encoding="utf-8")
        return RunInfo.from_json(content)
    except Exception as exc:
        raise CorruptedDataError(f"Failed to parse RunInfo from {p}: {exc}") from exc


def get_existing_trial_ids(trials_file: Union[Path, str]) -> set[str]:
    """Extract existing trial IDs from a trials.jsonl file."""
    p = Path(trials_file)
    if not p.is_file():
        return set()

    trial_ids: set[str] = set()
    with p.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            line_str = line.strip()
            if not line_str:
                continue
            try:
                data = json.loads(line_str)
                if isinstance(data, dict) and "trial_id" in data:
                    trial_ids.add(str(data["trial_id"]))
            except json.JSONDecodeError as exc:
                raise CorruptedDataError(
                    f"Malformed JSON on line {idx} of {p}: {exc}"
                ) from exc
    return trial_ids


def append_result(
    run_dir: Union[Path, str],
    trial: TrialResult,
    allow_duplicate: bool = False,
) -> Path:
    """
    Append a single TrialResult record to trials.jsonl.

    Args:
        run_dir: Directory containing trials.jsonl.
        trial: Validated TrialResult instance.
        allow_duplicate: If False, raises DuplicateTrialError if trial_id already exists.

    Returns:
        Path to trials.jsonl.
    """
    return append_results(run_dir, [trial], allow_duplicate=allow_duplicate)


def append_results(
    run_dir: Union[Path, str],
    trials: Iterable[TrialResult],
    allow_duplicate: bool = False,
) -> Path:
    """
    Append multiple TrialResult records to trials.jsonl in batch.

    Args:
        run_dir: Directory containing trials.jsonl.
        trials: Sequence or iterable of TrialResult instances.
        allow_duplicate: If False, checks for duplicate trial IDs.

    Returns:
        Path to trials.jsonl.
    """
    dir_path = Path(run_dir)
    dir_path.mkdir(parents=True, exist_ok=True)
    target_file = dir_path / "trials.jsonl"

    trials_list = list(trials)
    if not trials_list:
        return target_file

    if not allow_duplicate:
        existing_ids = get_existing_trial_ids(target_file)
        seen_batch: set[str] = set()
        for t in trials_list:
            if t.trial_id in existing_ids:
                raise DuplicateTrialError(
                    f"Trial ID {t.trial_id!r} already exists in {target_file}"
                )
            if t.trial_id in seen_batch:
                raise DuplicateTrialError(
                    f"Duplicate Trial ID {t.trial_id!r} found within the same append batch"
                )
            seen_batch.add(t.trial_id)

    # Append safely
    with target_file.open("a", encoding="utf-8") as f:
        for t in trials_list:
            f.write(t.to_json() + "\n")

    return target_file


def load_trials(
    trials_file: Union[Path, str],
    ignore_corrupted: bool = False,
) -> list[TrialResult]:
    """
    Load TrialResult records from trials.jsonl.

    Args:
        trials_file: Path to trials.jsonl or run directory.
        ignore_corrupted: If False, raises CorruptedDataError on malformed lines.

    Returns:
        List of loaded TrialResult objects.
    """
    p = Path(trials_file)
    if p.is_dir():
        p = p / "trials.jsonl"
    if not p.is_file():
        return []

    results: list[TrialResult] = []
    with p.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line_str = line.strip()
            if not line_str:
                continue
            try:
                data = json.loads(line_str)
                result = TrialResult.from_dict(data)
                results.append(result)
            except Exception as exc:
                if ignore_corrupted:
                    continue
                raise CorruptedDataError(
                    f"Failed to load TrialResult at {p}:{line_num}: {exc}"
                ) from exc

    return results


def load_run(run_dir: Union[Path, str]) -> tuple[RunInfo, list[TrialResult]]:
    """
    Load both authoritative files (run.json and trials.jsonl) from a run directory.

    Returns:
        Tuple of (RunInfo, list of TrialResult).
    """
    dir_path = Path(run_dir)
    run_info = load_run_info(dir_path / "run.json")
    trials = load_trials(dir_path / "trials.jsonl")
    return run_info, trials
