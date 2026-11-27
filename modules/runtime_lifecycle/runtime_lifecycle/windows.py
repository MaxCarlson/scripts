"""Windows Task Scheduler operations with ownership checks."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from .models import (
    ApplyResult,
    ElevationRequiredError,
    OwnershipConflictError,
    PreviewResult,
    TaskSnapshot,
    TaskSpec,
    TaskStatus,
    TaskSummary,
    UnsupportedPlatformError,
    current_user_sid,
    normalize_sid,
)
from .xml import ParsedTask, parse_task_xml, render_task_xml, semantic_diff, spec_hash


HRESULTS = {
    0x00000000: "The operation completed successfully",
    0x00041301: "The task is currently running",
    0x00041303: "The task has not yet run",
    0x00041304: "The task is disabled",
    0x00041306: "The task was terminated by the user",
    0x8004130F: "The task is not registered",
    0x8004131F: "An instance of this task is already running",
}
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_TASK_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]*$")

_INFO_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$target = $env:RUNTIME_LIFECYCLE_TASK_PATH
$task = Get-ScheduledTask | Where-Object { ($_.TaskPath + $_.TaskName) -eq $target } | Select-Object -First 1
if ($null -eq $task) {
  [pscustomobject]@{ missing = $true } | ConvertTo-Json -Compress
} else {
  $info = Get-ScheduledTaskInfo -InputObject $task
  [pscustomobject]@{
    missing = $false
    state = [string]$task.State
    lastRun = if ($info.LastRunTime -and $info.LastRunTime.Year -gt 1) { $info.LastRunTime.ToString('o') } else { $null }
    nextRun = if ($info.NextRunTime -and $info.NextRunTime.Year -gt 1) { $info.NextRunTime.ToString('o') } else { $null }
    missedRuns = [int]$info.NumberOfMissedRuns
    lastResult = [long]$info.LastTaskResult
  } | ConvertTo-Json -Compress
}
"""

_LIST_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$folder = $env:RUNTIME_LIFECYCLE_FOLDER
Get-ScheduledTask | Where-Object { $_.TaskPath.StartsWith($folder, [System.StringComparison]::OrdinalIgnoreCase) } |
  ForEach-Object { [pscustomobject]@{ path = $_.TaskPath + $_.TaskName; state = [string]$_.State } } |
  ConvertTo-Json -Compress
"""

_CREATE_FOLDER_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$target = $env:RUNTIME_LIFECYCLE_FOLDER
$service = New-Object -ComObject Schedule.Service
$service.Connect()
$current = $service.GetFolder('\')
foreach ($part in ($target.Trim('\') -split '\\')) {
  if (-not $part) { continue }
  $next = $current.Path.TrimEnd('\') + '\' + $part
  try { $current = $service.GetFolder($next) }
  catch { $current = $current.CreateFolder($part, $null) }
}
"ok"
"""


@dataclass(frozen=True, slots=True)
class _TaskInfo:
    state: str | None = None
    last_run: str | None = None
    next_run: str | None = None
    missed_runs: int | None = None
    last_result: int | None = None


def decode_hresult(result: int | None) -> str | None:
    """Decode a Task Scheduler result code, normalizing signed HRESULT values."""
    if result is None:
        return None
    code = result & 0xFFFFFFFF
    description = HRESULTS.get(code, "Unrecognized Task Scheduler result")
    return f"0x{code:08X}: {description}"


def is_elevated() -> bool:
    """Return whether the current Windows process has an elevated token."""
    if os.name != "nt":
        return False
    import ctypes

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _require_windows() -> None:
    if os.name != "nt":
        raise UnsupportedPlatformError("Windows Task Scheduler operations are supported on Windows only")


def _require_elevation(spec: TaskSpec) -> None:
    if (spec.principal.run_level == "highest" or spec.principal.mode == "system_service") and not is_elevated():
        raise ElevationRequiredError("This task principal requires an Administrator terminal")


def _powershell(script: str, env: dict[str, str]) -> str:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Could not run PowerShell Task Scheduler query: {exc}") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise RuntimeError(detail)
    return result.stdout.strip()


def _run_schtasks(arguments: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[bytes]:
    _require_windows()
    try:
        return subprocess.run(["schtasks.exe", *arguments], capture_output=True, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Could not execute schtasks.exe: {exc}") from exc


def _decode_process_text(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("mbcs", errors="replace")


def _task_info(task_path: str) -> _TaskInfo | None:
    env = os.environ.copy()
    env["RUNTIME_LIFECYCLE_TASK_PATH"] = task_path
    output = _powershell(_INFO_SCRIPT, env)
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Task Scheduler returned invalid status JSON: {output[:500]}") from exc
    if data.get("missing"):
        return None
    return _TaskInfo(
        state=data.get("state"),
        last_run=data.get("lastRun"),
        next_run=data.get("nextRun"),
        missed_runs=int(data["missedRuns"]) if data.get("missedRuns") is not None else None,
        last_result=int(data["lastResult"]) if data.get("lastResult") is not None else None,
    )


def _query_xml(task_path: str) -> bytes | None:
    result = _run_schtasks(["/Query", "/TN", task_path, "/XML"])
    if result.returncode:
        text = _decode_process_text(result.stderr + result.stdout).casefold()
        if any(token in text for token in ("cannot find", "does not exist", "not exist", "no scheduled task")):
            return None
        raise RuntimeError(f"Could not query task {task_path}: {_decode_process_text(result.stderr + result.stdout)}")
    return result.stdout


def _inspect(task_path: str) -> tuple[bytes, ParsedTask, _TaskInfo | None] | None:
    xml = _query_xml(task_path)
    if xml is None:
        return None
    try:
        parsed = parse_task_xml(xml)
    except Exception as exc:
        raise RuntimeError(f"Task {task_path} returned invalid XML: {exc}") from exc
    return xml, parsed, _task_info(task_path)


def _conflict_reason(parsed: ParsedTask, owner: str, name: str, principal_sid: str) -> str | None:
    if parsed.owner != owner or parsed.name != name:
        return "Task ownership marker is missing or belongs to a different owner/name"
    if parsed.principal_sid and parsed.principal_sid.upper() != principal_sid.upper():
        return "Task principal SID differs from the requested principal"
    if parsed.principal_sid is None:
        return "Task principal SID is missing"
    return None


def _task_path(owner: str, name: str, folder: str, task_name_override: str | None) -> str:
    if not _IDENTIFIER.fullmatch(owner) or not _IDENTIFIER.fullmatch(name):
        raise ValueError("owner and name must be lowercase task identifiers")
    if folder.casefold() != "\\scripts" and not folder.casefold().startswith("\\scripts\\"):
        raise ValueError("managed task folders must be under \\Scripts")
    if any(part in {"", ".", ".."} for part in folder.lstrip("\\").split("\\")):
        raise ValueError("folder contains an unsafe path segment")
    if any(any(char in part for char in ':*?"<>|/') for part in folder.lstrip("\\").split("\\")):
        raise ValueError("folder contains an invalid Task Scheduler name character")
    task_name = task_name_override or f"{owner}-{name}"
    if not _TASK_NAME.fullmatch(task_name) or task_name in {".", ".."}:
        raise ValueError("task name contains invalid characters")
    return f"{folder}\\{task_name}"


def _format_xml(data: bytes) -> str:
    return data.decode("utf-16")


def preview(spec: TaskSpec, *, check_paths: bool = False) -> PreviewResult:
    """Describe the create/update/no-op/conflict action without mutation."""
    _require_windows()
    task_path = spec.task_path
    rendered = render_task_xml(spec)
    if check_paths and (not spec.executable.is_file() or not spec.working_dir.is_dir()):
        missing = [
            str(path)
            for path, exists in (
                (spec.executable, spec.executable.is_file()),
                (spec.working_dir, spec.working_dir.is_dir()),
            )
            if not exists
        ]
        return PreviewResult(
            "conflict", task_path, _format_xml(rendered), reason=f"Task paths do not exist: {', '.join(missing)}"
        )
    existing = _inspect(task_path)
    if existing is None:
        return PreviewResult("create", task_path, _format_xml(rendered))
    _xml, parsed, _info = existing
    reason = _conflict_reason(parsed, spec.owner, spec.name, spec.principal_sid)
    if reason:
        return PreviewResult("conflict", task_path, _format_xml(rendered), reason=reason)
    differences = semantic_diff(spec, parsed)
    if parsed.spec_hash == spec_hash(spec) and not differences:
        return PreviewResult("noop", task_path, _format_xml(rendered))
    return PreviewResult("update", task_path, _format_xml(rendered), diff=differences)


def _create_folder(folder: str) -> None:
    env = os.environ.copy()
    env["RUNTIME_LIFECYCLE_FOLDER"] = folder
    _powershell(_CREATE_FOLDER_SCRIPT, env)


def _register_xml(task_path: str, xml: bytes) -> None:
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="runtime-lifecycle-", suffix=".xml", delete=False) as stream:
            temp_path = stream.name
            stream.write(xml)
        result = _run_schtasks(["/Create", "/XML", temp_path, "/TN", task_path, "/F"])
        if result.returncode:
            detail = _decode_process_text(result.stderr + result.stdout).strip()
            raise RuntimeError(f"Could not register task {task_path}: {detail}")
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


def apply(spec: TaskSpec, *, force: bool = False) -> ApplyResult:
    """Create or update an owned task; matching definitions are left untouched."""
    _require_windows()
    _require_elevation(spec)
    if not spec.executable.is_file():
        raise FileNotFoundError(f"Task executable does not exist: {spec.executable}")
    if not spec.working_dir.is_dir():
        raise FileNotFoundError(f"Task working directory does not exist: {spec.working_dir}")
    planned = preview(spec)
    if planned.action == "conflict" and not force:
        raise OwnershipConflictError(planned.reason or f"Task {spec.task_path} conflicts with the requested definition")
    if planned.action == "noop":
        return ApplyResult("unchanged", spec.task_path, status(spec.owner, spec.name, spec=spec))
    _create_folder(spec.folder)
    _register_xml(spec.task_path, render_task_xml(spec))
    verified = status(spec.owner, spec.name, spec=spec)
    if verified.registration_state != "registered":
        raise RuntimeError(
            f"Task registration verification failed: {verified.registration_state}: {verified.error or ''}"
        )
    return ApplyResult("created" if planned.action == "create" else "updated", spec.task_path, verified)


def status(
    owner: str,
    name: str,
    *,
    spec: TaskSpec | None = None,
    folder: str = "\\Scripts",
    task_name_override: str | None = None,
    principal_sid: str | None = None,
) -> TaskStatus:
    """Inspect ownership, semantic drift, Scheduler state, paths, and last result."""
    _require_windows()
    path = spec.task_path if spec else _task_path(owner, name, folder, task_name_override)
    existing = _inspect(path)
    if existing is None:
        return TaskStatus(path, "missing")
    _xml, parsed, info = existing
    if parsed.owner != owner or parsed.name != name or parsed.principal_sid is None:
        registration_state = "conflict"
        error = "Task is missing a valid runtime_lifecycle owner/name/principal marker"
    elif spec is None and parsed.principal_sid.upper() != normalize_sid(principal_sid or current_user_sid()):
        registration_state = "conflict"
        error = "Task principal SID differs from the current user"
    elif spec is not None and parsed.principal_sid.upper() != spec.principal_sid.upper():
        registration_state = "conflict"
        error = "Task principal SID differs from the requested principal"
    elif spec is not None and (parsed.spec_hash != spec_hash(spec) or semantic_diff(spec, parsed)):
        registration_state = "drifted"
        error = None
    else:
        registration_state = "registered"
        error = None
    last_result = info.last_result if info else None
    executable = Path(parsed.executable) if parsed.executable else None
    working = Path(parsed.working_dir) if parsed.working_dir else None
    return TaskStatus(
        task_path=path,
        registration_state=registration_state,
        state=info.state if info else None,
        enabled=parsed.enabled,
        principal_sid=parsed.principal_sid,
        logon_type=parsed.logon_type,
        run_level=parsed.run_level,
        logged_off_capable=parsed.logged_off_capable,
        executable=parsed.executable,
        arguments=parsed.arguments,
        working_dir=parsed.working_dir,
        last_run=info.last_run if info else None,
        next_run=info.next_run if info else None,
        missed_runs=info.missed_runs if info else None,
        last_result=last_result,
        last_result_hresult=decode_hresult(last_result),
        executable_exists=executable.is_file() if executable else False,
        working_dir_exists=working.is_dir() if working else False,
        error=error,
    )


def _owned_task(
    owner: str, name: str, *, folder: str, task_name_override: str | None, principal_sid: str | None
) -> str:
    path = _task_path(owner, name, folder, task_name_override)
    existing = _inspect(path)
    if existing is None:
        raise FileNotFoundError(f"Scheduled Task {path} is not registered")
    _xml, parsed, _info = existing
    expected_sid = normalize_sid(principal_sid or current_user_sid())
    reason = _conflict_reason(parsed, owner, name, expected_sid)
    if reason:
        raise OwnershipConflictError(reason)
    return path


def _require_task_mutation_elevation(task_path: str) -> None:
    existing = _inspect(task_path)
    if existing is None:
        raise FileNotFoundError(f"Scheduled Task {task_path} is not registered")
    _xml, parsed, _info = existing
    if (parsed.run_level == "HighestAvailable" or parsed.principal_sid == "S-1-5-18") and not is_elevated():
        raise ElevationRequiredError("Mutating a highest-privilege or SYSTEM task requires an Administrator terminal")


def _change(
    owner: str, name: str, option: str, *, folder: str, task_name_override: str | None, principal_sid: str | None
) -> None:
    _require_windows()
    path = _owned_task(owner, name, folder=folder, task_name_override=task_name_override, principal_sid=principal_sid)
    _require_task_mutation_elevation(path)
    result = _run_schtasks(["/Change", "/TN", path, option])
    if result.returncode:
        raise RuntimeError(f"Could not change task {path}: {_decode_process_text(result.stderr + result.stdout)}")


def enable(
    owner: str,
    name: str,
    *,
    folder: str = "\\Scripts",
    task_name_override: str | None = None,
    principal_sid: str | None = None,
) -> None:
    _change(owner, name, "/ENABLE", folder=folder, task_name_override=task_name_override, principal_sid=principal_sid)


def disable(
    owner: str,
    name: str,
    *,
    folder: str = "\\Scripts",
    task_name_override: str | None = None,
    principal_sid: str | None = None,
) -> None:
    _change(owner, name, "/DISABLE", folder=folder, task_name_override=task_name_override, principal_sid=principal_sid)


def start(
    owner: str,
    name: str,
    *,
    folder: str = "\\Scripts",
    task_name_override: str | None = None,
    principal_sid: str | None = None,
) -> None:
    _require_windows()
    path = _owned_task(owner, name, folder=folder, task_name_override=task_name_override, principal_sid=principal_sid)
    _require_task_mutation_elevation(path)
    result = _run_schtasks(["/Run", "/TN", path])
    if result.returncode:
        raise RuntimeError(f"Could not start task {path}: {_decode_process_text(result.stderr + result.stdout)}")


def stop(
    owner: str,
    name: str,
    *,
    folder: str = "\\Scripts",
    task_name_override: str | None = None,
    principal_sid: str | None = None,
) -> None:
    _require_windows()
    path = _owned_task(owner, name, folder=folder, task_name_override=task_name_override, principal_sid=principal_sid)
    _require_task_mutation_elevation(path)
    result = _run_schtasks(["/End", "/TN", path])
    if result.returncode:
        raise RuntimeError(
            f"Could not stop scheduled action {path}: {_decode_process_text(result.stderr + result.stdout)}"
        )


def remove(
    owner: str,
    name: str,
    *,
    folder: str = "\\Scripts",
    task_name_override: str | None = None,
    principal_sid: str | None = None,
) -> bool:
    """Remove an owned task, refusing unmarked, foreign, or wrong-principal tasks."""
    _require_windows()
    path = _task_path(owner, name, folder, task_name_override)
    existing = _inspect(path)
    if existing is None:
        return False
    _owned_task(owner, name, folder=folder, task_name_override=task_name_override, principal_sid=principal_sid)
    _require_task_mutation_elevation(path)
    result = _run_schtasks(["/Delete", "/TN", path, "/F"])
    if result.returncode:
        raise RuntimeError(f"Could not remove task {path}: {_decode_process_text(result.stderr + result.stdout)}")
    return True


def snapshot(
    owner: str,
    name: str,
    *,
    folder: str = "\\Scripts",
    task_name_override: str | None = None,
    principal_sid: str | None = None,
) -> TaskSnapshot:
    """Capture exact XML and enabled state for a verified owned task."""
    _require_windows()
    path = _task_path(owner, name, folder, task_name_override)
    _owned_task(owner, name, folder=folder, task_name_override=task_name_override, principal_sid=principal_sid)
    xml = _query_xml(path)
    if xml is None:
        raise FileNotFoundError(f"Scheduled Task {path} disappeared during snapshot")
    parsed = parse_task_xml(xml)
    return TaskSnapshot(
        path, owner, name, parsed.principal_sid or "", xml, hashlib.sha256(xml).hexdigest(), parsed.enabled
    )


def restore(task_snapshot: TaskSnapshot) -> ApplyResult:
    """Restore a verified owned snapshot after confirming its integrity."""
    _require_windows()
    if hashlib.sha256(task_snapshot.xml).hexdigest() != task_snapshot.sha256:
        raise ValueError("Task snapshot XML hash does not match the recorded SHA-256")
    try:
        folder, task_name = task_snapshot.task_path.rsplit("\\", 1)
        expected_path = _task_path(task_snapshot.owner, task_snapshot.name, folder, task_name)
    except (ValueError, AttributeError) as exc:
        raise ValueError("Task snapshot path is invalid") from exc
    if expected_path != task_snapshot.task_path:
        raise ValueError("Task snapshot path is not canonical")
    parsed = parse_task_xml(task_snapshot.xml)
    reason = _conflict_reason(parsed, task_snapshot.owner, task_snapshot.name, task_snapshot.principal_sid)
    if reason:
        raise OwnershipConflictError(f"Snapshot is not a verified owned definition: {reason}")
    if (parsed.run_level == "HighestAvailable" or parsed.principal_sid == "S-1-5-18") and not is_elevated():
        raise ElevationRequiredError("Restoring a highest-privilege or SYSTEM task requires an Administrator terminal")
    existing = _inspect(task_snapshot.task_path)
    if existing is not None:
        _xml, current, _info = existing
        current_reason = _conflict_reason(current, task_snapshot.owner, task_snapshot.name, task_snapshot.principal_sid)
        if current_reason:
            raise OwnershipConflictError(f"Cannot restore over a conflicting task: {current_reason}")
    _create_folder(task_snapshot.task_path.rsplit("\\", 1)[0])
    _register_xml(task_snapshot.task_path, task_snapshot.xml)
    info = status(
        task_snapshot.owner,
        task_snapshot.name,
        folder=task_snapshot.task_path.rsplit("\\", 1)[0],
        task_name_override=task_snapshot.task_path.rsplit("\\", 1)[1],
        principal_sid=task_snapshot.principal_sid,
    )
    if info.registration_state != "registered":
        raise RuntimeError(f"Task snapshot restore verification failed: {info.registration_state}")
    return ApplyResult("updated" if existing else "created", task_snapshot.task_path, info)


def list_tasks(*, owner: str | None = None, folder: str = "\\Scripts") -> list[TaskSummary]:
    """Enumerate valid runtime_lifecycle-owned tasks under a folder."""
    _require_windows()
    env = os.environ.copy()
    env["RUNTIME_LIFECYCLE_FOLDER"] = folder.rstrip("\\") + "\\"
    output = _powershell(_LIST_SCRIPT, env)
    if not output:
        return []
    try:
        rows = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Task Scheduler returned invalid task list JSON: {output[:500]}") from exc
    if isinstance(rows, dict):
        rows = [rows]
    summaries: list[TaskSummary] = []
    for row in rows:
        path = row.get("path", "")
        existing = _inspect(path)
        if existing is None:
            continue
        _xml, parsed, info = existing
        if parsed.owner is None or parsed.name is None or (owner is not None and parsed.owner != owner):
            continue
        if parsed.spec_hash is None:
            continue
        last_result = info.last_result if info else None
        executable = Path(parsed.executable) if parsed.executable else None
        working_dir = Path(parsed.working_dir) if parsed.working_dir else None
        summaries.append(
            TaskSummary(
                task_path=path,
                owner=parsed.owner,
                name=parsed.name,
                state=info.state if info else row.get("state"),
                enabled=parsed.enabled,
                last_result=last_result,
                last_result_hresult=decode_hresult(last_result),
                logged_off_capable=parsed.logged_off_capable,
                executable=parsed.executable,
                executable_exists=executable.is_file() if executable else False,
                working_dir=parsed.working_dir,
                working_dir_exists=working_dir.is_dir() if working_dir else False,
            )
        )
    return sorted(summaries, key=lambda item: item.task_path.casefold())
