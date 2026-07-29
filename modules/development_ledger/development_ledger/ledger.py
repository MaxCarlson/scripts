"""Append-only event storage and Git provenance helpers."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

LEDGER_FILENAME = "RUNS.jsonl"


class LedgerError(RuntimeError):
    """Raised when ledger persistence or Git inspection fails."""


def read_events(output_dir: Path) -> list[dict[str, Any]]:
    """Read all valid JSONL events from an output directory."""

    path = output_dir / LEDGER_FILENAME
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LedgerError(f"Invalid JSON on line {line_number} of {path}: {exc}") from exc
        if not isinstance(event, dict):
            raise LedgerError(f"Event on line {line_number} of {path} is not an object.")
        events.append(event)
    return events


def append_event(output_dir: Path, event: dict[str, Any]) -> None:
    """Append one immutable event, rejecting duplicate event IDs."""

    output_dir.mkdir(parents=True, exist_ok=True)
    existing = read_events(output_dir)
    event_id = event.get("event_id")
    if not event_id:
        raise LedgerError("Cannot append an event without event_id.")
    if any(item.get("event_id") == event_id for item in existing):
        raise LedgerError(f"Event ID {event_id!r} already exists in {output_dir / LEDGER_FILENAME}.")

    path = output_dir / LEDGER_FILENAME
    payload = json.dumps(event, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(descriptor, payload.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def git_provenance(repo_root: Path, *, baseline_commit: str = "") -> dict[str, Any]:
    """Capture branch, commit, worktree, and optional commit-range change metadata."""

    branch = _git(repo_root, "branch", "--show-current", allow_empty=True)
    commit = _git(repo_root, "rev-parse", "HEAD")
    status_lines = _git(repo_root, "status", "--short", allow_empty=True).splitlines()
    changed_files: list[dict[str, Any]] = []
    diff_stat = ""
    if baseline_commit and baseline_commit != commit:
        name_status = _git(repo_root, "diff", "--name-status", f"{baseline_commit}..{commit}", allow_empty=True)
        for line in name_status.splitlines():
            parts = line.split("\t")
            if parts:
                changed_files.append({"status": parts[0], "paths": parts[1:]})
        diff_stat = _git(repo_root, "diff", "--stat", f"{baseline_commit}..{commit}", allow_empty=True)

    return {
        "repo_root": str(repo_root.resolve()),
        "branch": branch,
        "commit": commit,
        "baseline_commit": baseline_commit,
        "working_tree_clean": not status_lines,
        "working_tree_status": status_lines,
        "changed_files": changed_files,
        "diff_stat": diff_stat,
    }


def _git(repo_root: Path, *arguments: str, allow_empty: bool = False) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise LedgerError(f"Unable to execute Git in {repo_root}: {exc}") from exc
    if completed.returncode != 0:
        raise LedgerError(
            f"Git command failed ({completed.returncode}): git -C {repo_root} {' '.join(arguments)}\n"
            f"{completed.stderr.strip()}"
        )
    output = completed.stdout.strip()
    if not output and not allow_empty:
        raise LedgerError(f"Git command returned no output: git -C {repo_root} {' '.join(arguments)}")
    return output
