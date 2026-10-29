"""Versioned project-scoped task checkpoints and stale-aware recovery packets."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import subprocess
import tempfile
from typing import Any
import uuid

SCHEMA_VERSION = 1
MAX_CHECKPOINT_BYTES = 256 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 200
MAX_TEXT_LENGTH = 16 * 1024
MAX_SESSION_CHECKPOINTS = 2000
IDENTITY_FIELDS = {
    "session_id", "job_id", "message_id", "directory", "provider_id", "model_id", "worker_agent",
}


class CheckpointError(ValueError):
    """Invalid or unsafe checkpoint request/state."""


def _workspace(value: str | os.PathLike[str]) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink() or _is_junction(path):
        raise CheckpointError("Workspace must not be a symlink or junction")
    try:
        root = path.resolve(strict=True)
    except OSError as exc:
        raise CheckpointError(f"Workspace does not exist: {path}") from exc
    if not root.is_dir():
        raise CheckpointError("Workspace must be a directory")
    return root


def _is_junction(path: Path) -> bool:
    check = getattr(path, "is_junction", None)
    return bool(check and check())


def _project_root(workspace: Path) -> Path:
    executable = shutil_which_git()
    if executable:
        try:
            result = subprocess.run(
                [executable, "-C", str(workspace), "rev-parse", "--show-toplevel"],
                check=True, capture_output=True, text=True, encoding="utf-8", errors="strict", timeout=2,
            )
            root = Path(result.stdout.strip()).resolve(strict=True)
            workspace.relative_to(root)
            return root
        except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
            pass
    return workspace


def shutil_which_git() -> str | None:
    # Import lazily so checkpoint serialization itself stays on standard-library APIs.
    import shutil

    return shutil.which("git")


def _revision(project_root: Path) -> str | None:
    executable = shutil_which_git()
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, "-C", str(project_root), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, encoding="ascii", errors="strict", timeout=2,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None
    value = result.stdout.strip()
    return value if value and len(value) <= 128 else None


def _project_key(project_root: Path) -> str:
    identity = os.path.normcase(str(project_root)).casefold() if os.name == "nt" else str(project_root)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _safe_relative(value: str | os.PathLike[str], label: str) -> str:
    raw = os.fspath(value)
    windows = PureWindowsPath(raw)
    if (not raw or "\0" in raw or Path(raw).is_absolute() or windows.is_absolute() or windows.drive
            or any(part in {"", ".", ".."} for part in raw.replace("\\", "/").split("/"))):
        raise CheckpointError(f"{label} must be a relative workspace path: {raw!r}")
    return PurePosixPath(*raw.replace("\\", "/").split("/")).as_posix()


def _bounded_text(value: Any, label: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH or (not allow_empty and not value.strip()):
        raise CheckpointError(f"{label} must be text no longer than {MAX_TEXT_LENGTH} characters")
    return value


def _text_list(values: Any, label: str, *, paths: bool = False) -> list[str]:
    if not isinstance(values, (list, tuple)) or len(values) > MAX_ITEMS:
        raise CheckpointError(f"{label} must contain at most {MAX_ITEMS} entries")
    output = []
    for value in values:
        text = _bounded_text(value, label, allow_empty=False)
        output.append(_safe_relative(text, label) if paths else text)
    return list(dict.fromkeys(output))


def _source_evidence(workspace: Path, item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise CheckpointError("confirmed_sources entries must be objects")
    path = _safe_relative(item.get("path", ""), "confirmed source path")
    target = workspace.joinpath(*PurePosixPath(path).parts)
    try:
        resolved = target.resolve(strict=True)
        resolved.relative_to(workspace)
    except (OSError, ValueError) as exc:
        raise CheckpointError(f"Confirmed source escapes or is missing inside the workspace: {path}") from exc
    if not resolved.is_file():
        raise CheckpointError(f"Confirmed source is not a regular file: {path}")
    start, end = item.get("start_line"), item.get("end_line")
    if (start is None) != (end is None):
        raise CheckpointError("Confirmed source ranges require both start_line and end_line")
    if start is not None and (type(start) is not int or type(end) is not int or start <= 0 or end < start):
        raise CheckpointError("Confirmed source lines must be a valid inclusive one-based range")
    try:
        if resolved.stat().st_size > MAX_SOURCE_BYTES:
            raise CheckpointError(f"Confirmed source exceeds the {MAX_SOURCE_BYTES}-byte evidence limit: {path}")
        content = resolved.read_bytes()
    except OSError as exc:
        raise CheckpointError(f"Unable to read confirmed source: {path}") from exc
    if b"\0" in content:
        raise CheckpointError(f"Confirmed source is binary: {path}")
    try:
        line_count = len(content.decode("utf-8").splitlines())
    except UnicodeDecodeError as exc:
        raise CheckpointError(f"Confirmed source is not UTF-8 text: {path}") from exc
    if start is not None and end > line_count:
        raise CheckpointError(f"Confirmed source range exceeds the current file: {path}")
    result: dict[str, Any] = {"path": path, "sha256": hashlib.sha256(content).hexdigest()}
    if start is not None:
        result["start_line"] = start
        result["end_line"] = end
    return result


def _state_dir(workspace: Path, state_dir: str | os.PathLike[str] | None) -> Path:
    configured = state_dir or os.environ.get("LOCAL_AGENT_CHECKPOINT_ROOT")
    candidate = Path(configured).expanduser() if configured else Path.home() / ".local/share/local-agent/checkpoints"
    candidate = candidate.absolute()
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(workspace)
    except ValueError:
        return resolved
    raise CheckpointError("Checkpoint state must be outside the working tree")


def _checkpoint_path(state: Path, project_key: str, task_id: str) -> Path:
    task_key = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
    return state / project_key / f"{task_key}.json"


def _validate_identities(value: Any, workspace: Path) -> dict[str, str]:
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - IDENTITY_FIELDS:
        raise CheckpointError("identities must contain only known session, job, provider, model, and worker fields")
    result = {}
    for key, item in value.items():
        text = _bounded_text(item, f"identities.{key}", allow_empty=False)
        if key == "directory" and Path(text).expanduser().resolve(strict=False) != workspace:
            raise CheckpointError("Recorded directory identity must match the canonical workspace")
        result[key] = text
    result.setdefault("directory", str(workspace))
    return result


def _validate_checkpoint_shape(value: Any, workspace: Path) -> dict[str, Any]:
    if isinstance(value, dict) and (
        type(value.get("schema_version")) is not int
        or value.get("schema_version") != SCHEMA_VERSION
    ):
        raise CheckpointError("Unsupported checkpoint schema")
    required = {
        "schema_version", "checkpoint_id", "task_id", "objective", "authorized_scope",
        "project_identity", "base_revision", "identities", "confirmed_sources", "decisions",
        "assumptions", "modified_paths", "completed_verification", "pending_checks", "blockers",
        "next_action", "created_at", "updated_at",
    }
    if not isinstance(value, dict) or not required.issubset(value):
        raise CheckpointError("Checkpoint is missing required fields")
    if (not isinstance(value["task_id"], str) or not value["task_id"] or len(value["task_id"]) > 200
            or not isinstance(value["checkpoint_id"], str) or not value["checkpoint_id"]):
        raise CheckpointError("Checkpoint task and identity fields are invalid")
    _bounded_text(value["objective"], "objective", allow_empty=False)
    _bounded_text(value["next_action"], "next_action", allow_empty=False)
    identity = value["project_identity"]
    if (not isinstance(identity, dict) or not all(isinstance(identity.get(key), str) and identity[key]
            for key in ("project_root", "workspace", "project_key"))
            or not re.fullmatch(r"[0-9a-f]{64}", identity["project_key"])):
        raise CheckpointError("Checkpoint project identity is invalid")
    if not isinstance(value["base_revision"], (str, type(None))) or (
            isinstance(value["base_revision"], str) and len(value["base_revision"]) > 128):
        raise CheckpointError("Checkpoint base revision is invalid")
    _validate_identities(value["identities"], workspace)
    for key, paths in (("authorized_scope", True), ("modified_paths", True)):
        _text_list(value[key], key, paths=paths)
    for key in ("decisions", "assumptions", "completed_verification", "pending_checks", "blockers"):
        _text_list(value[key], key)
    sources = value["confirmed_sources"]
    if not isinstance(sources, list) or len(sources) > MAX_ITEMS:
        raise CheckpointError("Checkpoint source evidence is invalid")
    for item in sources:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise CheckpointError("Checkpoint source evidence is invalid")
        _safe_relative(item["path"], "confirmed source path")
        if not isinstance(item.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise CheckpointError("Checkpoint source digest is invalid")
        start, end = item.get("start_line"), item.get("end_line")
        if (start is None) != (end is None) or (start is not None and
                (type(start) is not int or type(end) is not int or start <= 0 or end < start)):
            raise CheckpointError("Checkpoint source line range is invalid")
    if not all(isinstance(value.get(key), str) and value[key] for key in ("created_at", "updated_at")):
        raise CheckpointError("Checkpoint timestamps are invalid")
    return value


def save_checkpoint(
    workspace: str | os.PathLike[str],
    task_id: str,
    objective: str,
    *,
    authorized_scope: list[str],
    next_action: str,
    state_dir: str | os.PathLike[str] | None = None,
    base_revision: str | None = None,
    identities: dict[str, str] | None = None,
    confirmed_sources: list[dict[str, Any]] | None = None,
    decisions: list[str] | None = None,
    assumptions: list[str] | None = None,
    modified_paths: list[str] | None = None,
    completed_verification: list[str] | None = None,
    pending_checks: list[str] | None = None,
    blockers: list[str] | None = None,
) -> dict[str, Any]:
    """Validate and atomically persist the latest checkpoint for a project/task."""
    root = _workspace(workspace)
    if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 200:
        raise CheckpointError("task_id must be non-empty text no longer than 200 characters")
    objective = _bounded_text(objective, "objective", allow_empty=False)
    next_action = _bounded_text(next_action, "next_action", allow_empty=False)
    revision = base_revision if base_revision is not None else _revision(_project_root(root))
    if revision is not None and (not isinstance(revision, str) or not revision or len(revision) > 128):
        raise CheckpointError("base_revision must be non-empty text no longer than 128 characters")
    project_root = _project_root(root)
    project_key = _project_key(project_root)
    state = _state_dir(project_root, state_dir)
    sources = confirmed_sources or []
    if not isinstance(sources, list) or len(sources) > MAX_ITEMS:
        raise CheckpointError(f"confirmed_sources must contain at most {MAX_ITEMS} entries")
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    checkpoint: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "checkpoint_id": str(uuid.uuid4()),
        "task_id": task_id,
        "objective": objective,
        "authorized_scope": _text_list(authorized_scope, "authorized_scope", paths=True),
        "project_identity": {"project_root": str(project_root), "workspace": str(root), "project_key": project_key},
        "base_revision": revision,
        "identities": _validate_identities(identities, root),
        "confirmed_sources": [_source_evidence(root, item) for item in sources],
        "decisions": _text_list(decisions or [], "decisions"),
        "assumptions": _text_list(assumptions or [], "assumptions"),
        "modified_paths": _text_list(modified_paths or [], "modified_paths", paths=True),
        "completed_verification": _text_list(completed_verification or [], "completed_verification"),
        "pending_checks": _text_list(pending_checks or [], "pending_checks"),
        "blockers": _text_list(blockers or [], "blockers"),
        "next_action": next_action,
        "created_at": now,
        "updated_at": now,
    }
    path = _checkpoint_path(state, project_key, task_id)
    _atomic_json(path, checkpoint)
    return {**checkpoint, "checkpoint_path": str(path)}


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or _is_junction(path.parent) or path.is_symlink():
        raise CheckpointError("Checkpoint path must not be a symlink or junction")
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(payload) > MAX_CHECKPOINT_BYTES:
        raise CheckpointError(f"Checkpoint exceeds {MAX_CHECKPOINT_BYTES} bytes")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def load_checkpoint(
    workspace: str | os.PathLike[str], task_id: str, *, state_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Load a checkpoint only when it belongs to this canonical project/workspace."""
    root = _workspace(workspace)
    if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 200:
        raise CheckpointError("task_id must be non-empty text no longer than 200 characters")
    project_root = _project_root(root)
    project_key = _project_key(project_root)
    path = _checkpoint_path(_state_dir(project_root, state_dir), project_key, task_id)
    try:
        if path.is_symlink() or _is_junction(path):
            raise CheckpointError("Checkpoint file must not be a symlink or junction")
        if path.stat().st_size > MAX_CHECKPOINT_BYTES:
            raise CheckpointError(f"Checkpoint exceeds {MAX_CHECKPOINT_BYTES} bytes")
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CheckpointError(f"No checkpoint found for task {task_id!r}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CheckpointError(f"Unable to read checkpoint for task {task_id!r}: {exc}") from exc
    _validate_checkpoint_shape(checkpoint, root)
    identity = checkpoint.get("project_identity")
    if (not isinstance(identity, dict) or identity.get("project_key") != project_key
            or identity.get("project_root") != str(project_root) or identity.get("workspace") != str(root)
            or checkpoint.get("task_id") != task_id):
        raise CheckpointError("Checkpoint belongs to a different project or workspace")
    return {**checkpoint, "checkpoint_path": str(path)}


def recovery_packet(workspace: str | os.PathLike[str], checkpoint: dict[str, Any]) -> dict[str, Any]:
    """Return compact status and next-step evidence; never contact or restart a worker."""
    if not isinstance(checkpoint, dict) or checkpoint.get("schema_version") != SCHEMA_VERSION:
        raise CheckpointError("Unsupported checkpoint schema")
    root = _workspace(workspace)
    _validate_checkpoint_shape(checkpoint, root)
    identity = checkpoint.get("project_identity", {})
    if identity.get("workspace") != str(root) or identity.get("project_root") != str(_project_root(root)):
        raise CheckpointError("Checkpoint belongs to a different project or workspace")
    stale_reasons: list[str] = []
    current_revision = _revision(Path(identity["project_root"]))
    expected_revision = checkpoint.get("base_revision")
    if expected_revision:
        if current_revision is None:
            stale_reasons.append("base_revision_unavailable")
        elif expected_revision != current_revision:
            stale_reasons.append("base_revision_changed")
    evidence = []
    for item in checkpoint.get("confirmed_sources", []):
        try:
            current = _source_evidence(root, {key: item[key] for key in ("path", "start_line", "end_line") if key in item})
        except CheckpointError as exc:
            evidence.append({"path": item.get("path"), "status": "stale", "reason": str(exc)})
            stale_reasons.append(f"source_unavailable:{item.get('path', '')}")
            continue
        is_current = current["sha256"] == item.get("sha256")
        if not is_current:
            stale_reasons.append(f"source_changed:{item['path']}")
        evidence.append({"path": item["path"], "status": "current" if is_current else "stale",
                         "expected_sha256": item.get("sha256"), "current_sha256": current["sha256"],
                         **({"start_line": item["start_line"], "end_line": item["end_line"]}
                            if "start_line" in item else {})})
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": checkpoint["task_id"],
        "objective": checkpoint["objective"],
        "status": "stale" if stale_reasons else "current",
        "stale_reasons": sorted(set(stale_reasons)),
        "authorized_scope": checkpoint["authorized_scope"],
        "identities": checkpoint["identities"],
        "confirmed_sources": checkpoint["confirmed_sources"],
        "source_evidence": evidence,
        "decisions": checkpoint["decisions"],
        "assumptions": checkpoint["assumptions"],
        "modified_paths": checkpoint["modified_paths"],
        "completed_verification": checkpoint["completed_verification"],
        "pending_checks": checkpoint["pending_checks"],
        "blockers": checkpoint["blockers"],
        "next_action": checkpoint["next_action"],
        "automatic_resubmission": False,
        "recovery_rules": [
            "Do not submit a duplicate job based on this checkpoint alone.",
            "Reconcile the stored session, initiating message, and job identity before any follow-up.",
            "Review stale evidence and changed paths before using prior conclusions.",
        ],
    }


def recover_session(
    workspace: str | os.PathLike[str],
    session_id: str,
    *,
    state_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Find the latest checkpoint for a session and revalidate all evidence."""
    if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > MAX_TEXT_LENGTH:
        raise CheckpointError("session_id must be non-empty text within the checkpoint text limit")
    root = _workspace(workspace)
    project_root = _project_root(root)
    project_key = _project_key(project_root)
    directory = _state_dir(project_root, state_dir) / project_key
    if directory.is_symlink() or _is_junction(directory):
        raise CheckpointError("Checkpoint project directory must not be a symlink or junction")
    try:
        files = sorted(directory.glob("*.json"), key=lambda path: path.name)
    except OSError as exc:
        raise CheckpointError(f"Unable to list session checkpoints: {exc}") from exc
    if len(files) > MAX_SESSION_CHECKPOINTS:
        raise CheckpointError(f"Session recovery is limited to {MAX_SESSION_CHECKPOINTS} project checkpoints")
    matches: list[dict[str, Any]] = []
    for path in files:
        if path.is_symlink() or _is_junction(path):
            continue
        try:
            if path.stat().st_size > MAX_CHECKPOINT_BYTES:
                continue
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("identities", {}).get("session_id") != session_id:
                continue
            task_id = value.get("task_id")
            if not isinstance(task_id, str) or _checkpoint_path(directory.parent, project_key, task_id) != path:
                continue
            _validate_checkpoint_shape(value, root)
            if value.get("project_identity", {}).get("workspace") != str(root):
                continue
            matches.append(value)
        except (OSError, UnicodeError, json.JSONDecodeError, CheckpointError, AttributeError, TypeError):
            continue
    if not matches:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "missing",
            "session_id": session_id,
            "automatic_resubmission": False,
        }
    latest = max(matches, key=lambda item: (item["updated_at"], item["task_id"]))
    loaded = load_checkpoint(root, latest["task_id"], state_dir=state_dir)
    return recovery_packet(root, loaded)
