"""Read-only package, executable, and registry schema compatibility diagnostics."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def evaluate_deployment_preflight(
    *,
    current_schema: int | None,
    target_schema: int | None,
    pending_launches: int | None,
    open_terminal_launches: int | None,
    process_enumeration: str,
    active_writers: int | None = 0,
) -> dict[str, Any]:
    """Classify an upgrade without changing the registry or installing packages."""
    if current_schema is None or target_schema is None:
        return {
            "ready": False,
            "kind": "unknown_schema",
            "current_schema": current_schema,
            "target_schema": target_schema,
            "blockers": ["Current and target registry schema versions must both be known."],
        }
    if target_schema < current_schema:
        return {
            "ready": False,
            "kind": "unsupported_downgrade",
            "current_schema": current_schema,
            "target_schema": target_schema,
            "blockers": ["Schema downgrade is unsupported; use a compatible package or restore a verified backup."],
        }
    if target_schema == current_schema:
        return {
            "ready": True,
            "kind": "package_only",
            "current_schema": current_schema,
            "target_schema": target_schema,
            "blockers": [],
            "summary": "Package update does not require a registry schema transition.",
        }

    blockers: list[str] = []
    warnings: list[str] = []
    if pending_launches is None:
        blockers.append("Pending-launch state is unavailable; lifecycle ownership is uncertain.")
    elif pending_launches:
        blockers.append(f"Resolve {pending_launches} pending launch(es) before changing the registry schema.")
    if open_terminal_launches is None:
        blockers.append("Terminal-launch ownership state is unavailable.")
    elif open_terminal_launches and process_enumeration == "complete" and active_writers == 0:
        warnings.append(
            f"{open_terminal_launches} terminal launch record(s) remain open; no active LLMD writer was observed. "
            "Preserve them for exact post-upgrade reconciliation."
        )
    if process_enumeration != "complete":
        blockers.append("Complete process enumeration is required before changing the registry schema.")
    if active_writers is None:
        blockers.append("Active LLMD writer ownership is unknown.")
    elif active_writers:
        blockers.append(f"Stop {active_writers} active LLMD writer process(es) before changing the registry schema.")
    return {
        "ready": not blockers,
        "kind": "schema_transition",
        "current_schema": current_schema,
        "target_schema": target_schema,
        "blockers": blockers,
        "warnings": warnings,
        "summary": (
            "Registry schema transition is clear under the observed lifecycle evidence."
            if not blockers
            else "Do not begin the registry schema transition until every blocker is resolved."
        ),
    }


def count_active_llmd_writers(inventory: Any, *, current_pid: int | None = None) -> int | None:
    """Count likely LLMD/agents writer processes only when process enumeration is complete."""
    availability = getattr(getattr(inventory, "availability", None), "value", None)
    if availability != "complete":
        return None
    count = 0
    names = {"llmd", "llmd.exe", "llmd.cmd", "agents", "agents.exe", "agents.cmd"}
    for record in getattr(inventory, "records", ()):
        identity = getattr(record, "identity", None)
        if current_pid is not None and identity is not None and identity.pid == current_pid:
            continue
        image_name = str(getattr(record, "image_name", "") or "").casefold()
        argv = tuple(str(part).casefold() for part in (getattr(record, "argv", None) or ()))
        if image_name in names or any(Path(part).name in names for part in argv):
            count += 1
            continue
        if any("agent_continuity.dispatcher_cli" in part or "agent_continuity.cli" in part for part in argv):
            count += 1
    return count


def cli_path_candidates(path_value: str | None = None) -> dict[str, list[str]]:
    """Return every existing LLMD and agents command candidate on PATH in search order."""
    path_value = os.environ.get("PATH", "") if path_value is None else path_value
    out: dict[str, list[str]] = {}
    for command in ("llmd", "agents"):
        candidates: list[str] = []
        seen: set[str] = set()
        for directory in path_value.split(os.pathsep):
            if not directory:
                continue
            for suffix in (".exe", ".cmd", ".bat", ""):
                candidate = Path(directory) / f"{command}{suffix}"
                try:
                    if not candidate.is_file():
                        continue
                    resolved = str(candidate.resolve())
                except OSError:
                    continue
                key = os.path.normcase(resolved)
                if key not in seen:
                    seen.add(key)
                    candidates.append(resolved)
        out[command] = candidates
    return out


def installation_resolution(
    *, executable: str | None, module_path: str | None, path_candidates: dict[str, list[str]] | list[str],
) -> dict[str, Any]:
    """Describe the current CLI resolution and stale worktree command shims."""
    current = str(Path(executable).resolve()) if executable else None
    module = str(Path(module_path).resolve()) if module_path else None
    by_command = path_candidates if isinstance(path_candidates, dict) else {"llmd": path_candidates}
    all_candidates = [path for candidates in by_command.values() for path in candidates]
    conflicting_commands = [name for name, candidates in by_command.items() if len(candidates) > 1]
    other_candidates = [path for path in all_candidates if not current or os.path.normcase(path) != os.path.normcase(current)]
    stale = [
        path for path in other_candidates
        if ".codex\\worktrees\\" in path.casefold()
        or ".codex/worktrees/" in path.casefold()
        or "\\.worktree\\" in path.casefold()
        or "/.worktree/" in path.casefold()
    ]
    return {
        "status": "conflict" if conflicting_commands or stale else "ok",
        "invoked_executable": current,
        "imported_module": module,
        "path_candidates": {name: list(candidates) for name, candidates in by_command.items()},
        "path_candidate_count": {name: len(candidates) for name, candidates in by_command.items()},
        "conflicting_commands": conflicting_commands,
        "stale_candidates": stale,
        "guidance": (
            "Check which command appears first on PATH and compare it with the imported package path; no PATH changes were made."
            if conflicting_commands or stale
            else "No duplicate or worktree-local LLMD/agents command candidates were found on PATH."
        ),
    }
