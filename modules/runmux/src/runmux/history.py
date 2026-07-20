"""Repo-local command history and saved-command storage for runmux."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runmux.models import RunRecord, parse_iso_datetime, utc_now_iso
from runmux.platform_paths import get_state_dir

HISTORY_DIR_NAME = ".runmux"
HISTORY_FILE_NAME = "commands.json"
UNIQUE_COMMANDS_FILE_NAME = "unique_commands.json"


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
    name: str | None = None
    rows: int | None = None
    columns: int | None = None
    force_color: bool = True


def get_history_path() -> Path:
    """Return the repo-local runmux command history path."""

    module_root = Path(__file__).resolve().parents[2]
    return module_root / HISTORY_DIR_NAME / HISTORY_FILE_NAME


def history_path_for_state_dir(state_dir: Path) -> Path:
    """Route isolated registries away from the user's normal history file."""

    resolved_state = state_dir.expanduser().resolve()
    if resolved_state == get_state_dir().expanduser().resolve():
        return get_history_path()
    return resolved_state / HISTORY_FILE_NAME


def unique_commands_path(history_path: Path | None = None) -> Path:
    """Return the unique-command ledger beside the applicable history file."""

    if history_path is None or history_path.resolve() == get_history_path().resolve():
        return get_history_path().parent / UNIQUE_COMMANDS_FILE_NAME
    return history_path.resolve().parent / UNIQUE_COMMANDS_FILE_NAME


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
    record_unique_command_start(record, history_path=path)


def record_run_finished(
    run_id: str,
    *,
    status: str,
    runtime_seconds: float | None,
    exit_code: int | None = None,
    path: Path | None = None,
) -> None:
    """Update the matching history entry when a run exits."""

    data = load_data(path)
    changed = False
    for item in reversed(data["history"]):
        if item.get("run_id") == run_id:
            item["status"] = status
            item["ended_at"] = utc_now_iso()
            item["runtime_seconds"] = runtime_seconds
            item["exit_code"] = exit_code
            changed = True
            break
    if changed:
        save_data(data, path)
        record_unique_command_finish(
            run_id,
            status=status,
            runtime_seconds=runtime_seconds,
            history_path=path,
        )


def load_unique_commands(path: Path | None = None) -> dict[str, Any]:
    """Load the module-local ledger of unique commands and every recorded run."""

    data_path = unique_commands_path(path)
    if not data_path.exists():
        return {"commands": []}
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise HistoryError(f"Could not parse unique-command ledger: {data_path}") from error
    if not isinstance(data, dict) or not isinstance(data.get("commands", []), list):
        raise HistoryError(f"Invalid unique-command ledger: {data_path}")
    return data


def save_unique_commands(data: dict[str, Any], path: Path | None = None) -> None:
    """Persist the unique-command ledger."""

    data_path = unique_commands_path(path)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def record_unique_command_start(record: RunRecord, *, history_path: Path | None = None) -> None:
    """Append one exact effective-cwd run to its command's ledger entry."""

    argv = decode_argv(record.argv_json)
    data = load_unique_commands(history_path)
    command_line = record.command_line
    key = command_line.casefold()
    entry = next((item for item in data["commands"] if item.get("key") == key), None)
    started_at = record.started_at or record.created_at
    run = {
        "run_id": record.id,
        "started_at": started_at,
        "ended_at": None,
        "status": record.status,
        "runtime_seconds": None,
        "cwd": record.cwd,
    }
    if entry is None:
        entry = {
            "key": key,
            "command_line": command_line,
            "argv": argv,
            "first_run_at": started_at,
            "last_run_at": started_at,
            "run_count": 0,
            "paths": [],
            "runs": [],
        }
        data["commands"].append(entry)
    entry["run_count"] = int(entry.get("run_count", 0)) + 1
    entry["last_run_at"] = started_at
    if record.cwd not in entry["paths"]:
        entry["paths"].append(record.cwd)
    entry["runs"].append(run)
    save_unique_commands(data, history_path)


def record_unique_command_finish(
    run_id: str,
    *,
    status: str,
    runtime_seconds: float | None,
    history_path: Path | None = None,
) -> None:
    """Complete the matching unique-command run without deleting historical data."""

    data = load_unique_commands(history_path)
    for entry in data["commands"]:
        for run in reversed(entry.get("runs", [])):
            if run.get("run_id") == run_id:
                run["status"] = status
                run["ended_at"] = utc_now_iso()
                run["runtime_seconds"] = runtime_seconds
                save_unique_commands(data, history_path)
                return


def delete_saved_commands(ids: set[int], *, path: Path | None = None) -> list[SavedCommand]:
    """Delete selected saved-command records only, preserving all history/ledger data."""

    data = load_data(path)
    removed = [saved_from_dict(raw) for raw in data["saved_commands"] if int(raw.get("id", -1)) in ids]
    if removed:
        data["saved_commands"] = [raw for raw in data["saved_commands"] if int(raw.get("id", -1)) not in ids]
        save_data(data, path)
    return removed


def save_record_command(record: RunRecord, *, path: Path | None = None) -> SavedCommand:
    """Save a run record's command for later reuse."""

    argv = decode_argv(record.argv_json)
    try:
        env_overrides = json.loads(record.env_overrides_json)
    except json.JSONDecodeError:
        env_overrides = {}
    force_color = bool(isinstance(env_overrides, dict) and env_overrides.get("FORCE_COLOR") == "1")
    return save_command(
        argv=argv,
        command_line=record.command_line,
        cwd=record.cwd,
        name=record.name,
        rows=record.rows,
        columns=record.columns,
        force_color=force_color,
        path=path,
    )


def save_command(
    *,
    argv: list[str],
    command_line: str | None = None,
    cwd: str,
    name: str | None = None,
    rows: int | None = None,
    columns: int | None = None,
    force_color: bool = True,
    path: Path | None = None,
) -> SavedCommand:
    """Save argv and its execution context as a reusable command."""

    if not argv:
        raise HistoryError("Cannot save an empty command.")
    data = load_data(path)
    rendered = command_line or render_command_line(argv)
    for raw in data["saved_commands"]:
        if raw.get("command_line") == rendered and raw.get("cwd") == cwd:
            return saved_from_dict(raw)
    next_id = next_saved_id(data["saved_commands"])
    item = {
        "id": next_id,
        "base": command_base(argv),
        "argv": argv,
        "command_line": rendered,
        "cwd": cwd,
        "name": name,
        "rows": rows,
        "columns": columns,
        "force_color": force_color,
        "saved_at": utc_now_iso(),
        "last_run_at": None,
    }
    data["saved_commands"].append(item)
    save_data(data, path)
    return saved_from_dict(item)


def mark_saved_command_run(command_line: str, *, cwd: str | None = None, path: Path | None = None) -> None:
    """Record that a saved command was launched."""

    data = load_data(path)
    changed = False
    for raw in data["saved_commands"]:
        if raw.get("command_line") == command_line and (cwd is None or raw.get("cwd") == cwd):
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


def indexed_history_entries(path: Path | None = None) -> list[dict[str, Any]]:
    """Return newest-first history with global recency IDs.

    The newest complete-history entry is always ID 0. Callers must filter this
    result rather than enumerate filtered rows so displayed IDs remain valid
    selectors for ``runmux run --history --id``.
    """

    entries = [entry for entry in history_entries(path) if not is_internal_probe_entry(entry)]
    indexed: list[dict[str, Any]] = []
    for history_id, entry in enumerate(reversed(entries)):
        item = dict(entry)
        item["history_id"] = history_id
        indexed.append(item)
    return indexed


def is_internal_probe_entry(entry: dict[str, Any]) -> bool:
    """Identify legacy test/smoke entries that leaked into user history."""

    command = str(entry.get("command_line") or "").strip().casefold()
    cwd = str(entry.get("cwd") or "").replace("/", "\\").casefold()
    if ".pytest_tmp_root" in cwd or "pytest-of-" in cwd:
        return True
    if command == "python -v":
        return True
    if "print('runmux-ok')" in command or 'print("runmux-ok")' in command:
        return True
    return command in {"python -c print('history-smoke')", 'python -c print("history-smoke")'}


def history_entry_by_id(history_id: int, path: Path | None = None) -> dict[str, Any]:
    """Return one entry by its global newest-first history ID."""

    if history_id < 0:
        raise HistoryError("History ID must be zero or greater.")
    entries = indexed_history_entries(path)
    if not entries:
        raise HistoryError("Runmux history is empty.")
    if history_id >= len(entries):
        raise HistoryError(f"History ID {history_id} does not exist (available: 0-{len(entries) - 1}).")
    return entries[history_id]


def filter_history_entries(
    entries: list[dict[str, Any]],
    *,
    starts_with: str | None = None,
    contains: str | None = None,
) -> list[dict[str, Any]]:
    """Filter indexed entries without changing their global history IDs."""

    prefix = starts_with.casefold() if starts_with is not None else None
    needle = contains.casefold() if contains is not None else None
    filtered = []
    for entry in entries:
        command = str(entry.get("command_line") or "")
        folded = command.casefold()
        if prefix is not None and not folded.startswith(prefix):
            continue
        if needle is not None and needle not in folded:
            continue
        filtered.append(entry)
    return filtered


def most_common_history_entries(entries: list[dict[str, Any]], count: int = 10) -> list[dict[str, Any]]:
    """Group commands by text and return their most recent occurrence IDs."""

    if count <= 0:
        raise HistoryError("Most-common count must be greater than zero.")
    grouped: dict[str, dict[str, Any]] = {}
    for entry in entries:
        command = str(entry.get("command_line") or "")
        key = command.casefold()
        if key not in grouped:
            representative = dict(entry)
            representative["occurrence_count"] = 0
            grouped[key] = representative
        grouped[key]["occurrence_count"] += 1
    ordered = sorted(
        grouped.values(),
        key=lambda item: (-int(item["occurrence_count"]), int(item["history_id"])),
    )
    return ordered[:count]


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
        name=raw.get("name") if isinstance(raw.get("name"), str) else None,
        rows=raw.get("rows") if isinstance(raw.get("rows"), int) else None,
        columns=raw.get("columns") if isinstance(raw.get("columns"), int) else None,
        force_color=bool(raw.get("force_color", True)),
    )


def age_seconds(value: str | None) -> float | None:
    """Return age in seconds from an ISO timestamp."""

    parsed = parse_iso_datetime(value)
    if parsed is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())
