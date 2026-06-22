"""Repo-local command history and saved-command storage for runmux."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runmux.models import RunRecord, parse_iso_datetime, utc_now_iso

HISTORY_DIR_NAME = ".runmux"
HISTORY_FILE_NAME = "commands.json"


class HistoryError(RuntimeError):
    """Raised for command history errors."""


@dataclass(frozen=True)
class SavedCommand:
    """A manually saved command."""

    id: int
    base: str
    argv: list[str]
    command_line: str
    cwd: str
    saved_at: str
    last_run_at: str | None = None


def get_history_path() -> Path:
    """Return the repo-local runmux command history path."""

    module_root = Path(__file__).resolve().parents[2]
    return module_root / HISTORY_DIR_NAME / HISTORY_FILE_NAME


def load_data(path: Path | None = None) -> dict[str, Any]:
    """Load command history data."""

    data_path = path or get_history_path()
    if not data_path.exists():
        return {"history": [], "saved_commands": []}
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise HistoryError(f"Could not parse runmux history file: {data_path}") from error
    if not isinstance(data, dict):
        raise HistoryError(f"Invalid runmux history file: {data_path}")
    data.setdefault("history", [])
    data.setdefault("saved_commands", [])
    return data


def save_data(data: dict[str, Any], path: Path | None = None) -> None:
    """Write command history data."""

    data_path = path or get_history_path()
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def command_base(argv: list[str]) -> str:
    """Return the base command name for argv."""

    if not argv:
        return ""
    return Path(argv[0]).name


def record_run_started(record: RunRecord, *, path: Path | None = None) -> None:
    """Append a run start entry to history."""

    data = load_data(path)
    argv = decode_argv(record.argv_json)
    data["history"].append(
        {
            "run_id": record.id,
            "numeric_id": record.numeric_id,
            "base": command_base(argv),
            "argv": argv,
            "command_line": record.command_line,
            "cwd": record.cwd,
            "status": record.status,
            "started_at": record.started_at or record.created_at,
            "ended_at": None,
            "runtime_seconds": None,
        }
    )
    save_data(data, path)


def record_run_finished(
    run_id: str,
    *,
    status: str,
    runtime_seconds: float | None,
    path: Path | None = None,
) -> None:
    """Update the matching history entry when a run exits."""

    data = load_data(path)
    for item in reversed(data["history"]):
        if item.get("run_id") == run_id:
            item["status"] = status
            item["ended_at"] = utc_now_iso()
            item["runtime_seconds"] = runtime_seconds
            break
    save_data(data, path)


def save_record_command(record: RunRecord, *, path: Path | None = None) -> SavedCommand:
    """Save a run record's command for later reuse."""

    argv = decode_argv(record.argv_json)
    return save_command(argv=argv, command_line=record.command_line, cwd=record.cwd, path=path)


def save_command(
    *,
    argv: list[str],
    command_line: str | None = None,
    cwd: str,
    path: Path | None = None,
) -> SavedCommand:
    """Save argv as a reusable command if it is not already saved."""

    if not argv:
        raise HistoryError("Cannot save an empty command.")
    data = load_data(path)
    rendered = command_line or render_command_line(argv)
    for raw in data["saved_commands"]:
        if raw.get("command_line") == rendered:
            return saved_from_dict(raw)
    next_id = next_saved_id(data["saved_commands"])
    item = {
        "id": next_id,
        "base": command_base(argv),
        "argv": argv,
        "command_line": rendered,
        "cwd": cwd,
        "saved_at": utc_now_iso(),
        "last_run_at": None,
    }
    data["saved_commands"].append(item)
    save_data(data, path)
    return saved_from_dict(item)


def mark_saved_command_run(command_line: str, *, path: Path | None = None) -> None:
    """Record that a saved command was launched."""

    data = load_data(path)
    changed = False
    for raw in data["saved_commands"]:
        if raw.get("command_line") == command_line:
            raw["last_run_at"] = utc_now_iso()
            changed = True
            break
    if changed:
        save_data(data, path)


def list_saved_commands(path: Path | None = None) -> list[SavedCommand]:
    """Return saved commands sorted by base then command."""

    data = load_data(path)
    return sorted(
        [saved_from_dict(raw) for raw in data["saved_commands"]],
        key=lambda item: (item.base.lower(), item.command_line.lower()),
    )


def saved_bases(path: Path | None = None) -> list[str]:
    """Return saved command bases."""

    return sorted({item.base for item in list_saved_commands(path)})


def commands_for_base(base: str, path: Path | None = None) -> list[SavedCommand]:
    """Return saved commands for one base."""

    return [item for item in list_saved_commands(path) if item.base == base]


def history_entries(path: Path | None = None) -> list[dict[str, Any]]:
    """Return history entries in insertion order."""

    data = load_data(path)
    return list(data["history"])


def command_stats(path: Path | None = None) -> dict[str, Any]:
    """Return aggregate stats by base and saved command."""

    history = history_entries(path)
    saved = list_saved_commands(path)
    base_counts: dict[str, int] = {}
    for item in history:
        base = str(item.get("base") or "")
        base_counts[base] = base_counts.get(base, 0) + 1

    saved_stats = []
    for command in saved:
        matches = [item for item in history if item.get("command_line") == command.command_line]
        runtimes = [
            float(item["runtime_seconds"]) for item in matches if isinstance(item.get("runtime_seconds"), int | float)
        ]
        saved_stats.append(
            {
                "command": command,
                "run_count": len(matches),
                "average_runtime_seconds": sum(runtimes) / len(runtimes) if runtimes else None,
                "last_runtime_seconds": runtimes[-1] if runtimes else None,
                "last_run_age_seconds": (age_seconds(matches[-1].get("started_at")) if matches else None),
            }
        )
    return {"base_counts": base_counts, "saved": saved_stats}


def decode_argv(value: str) -> list[str]:
    """Decode argv JSON from a run record."""

    parsed = json.loads(value)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise HistoryError("Invalid argv metadata.")
    return parsed


def render_command_line(argv: list[str]) -> str:
    """Render argv for display."""

    return shlex.join(argv)


def next_saved_id(items: list[dict[str, Any]]) -> int:
    """Return the lowest available saved-command ID."""

    used = {int(item["id"]) for item in items if isinstance(item.get("id"), int)}
    candidate = 0
    while candidate in used:
        candidate += 1
    return candidate


def saved_from_dict(raw: dict[str, Any]) -> SavedCommand:
    """Convert a JSON object to SavedCommand."""

    argv = raw.get("argv")
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        argv = []
    return SavedCommand(
        id=int(raw.get("id", -1)),
        base=str(raw.get("base") or command_base(argv)),
        argv=argv,
        command_line=str(raw.get("command_line") or render_command_line(argv)),
        cwd=str(raw.get("cwd") or "."),
        saved_at=str(raw.get("saved_at") or ""),
        last_run_at=raw.get("last_run_at") if isinstance(raw.get("last_run_at"), str) else None,
    )


def age_seconds(value: str | None) -> float | None:
    """Return age in seconds from an ISO timestamp."""

    parsed = parse_iso_datetime(value)
    if parsed is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())
