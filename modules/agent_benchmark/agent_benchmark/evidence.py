"""Byte-exact checkpoints and isolated verification for trusted offline tasks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import platform
import shutil
import subprocess
import sys
import time
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class Task:
    path: Path
    task_id: str
    suite_version: str
    category: str
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    time_budget_seconds: float
    verifier: Path
    instruction: str


def _relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Task paths must be nonempty relative POSIX paths")
    path = PureWindowsPath(value)
    if path.is_absolute() or path.drive or any(part in ("..", ".", "") for part in value.split("/")):
        raise ValueError(f"Unsafe task path: {value}")
    return value


def load_task(path: Path) -> Task:
    path = path.resolve()
    manifest = json.loads((path / "task.json").read_text(encoding="utf-8"))
    allowed = tuple(_relative(p) for p in manifest["allowed_paths"])
    forbidden = tuple(_relative(p) for p in manifest["forbidden_paths"])
    verifier = path / _relative(manifest["verifier"])
    if not verifier.is_file() or not verifier.resolve().is_relative_to(path):
        raise ValueError("Verifier must be a file inside the trusted task directory")
    budget = float(manifest["time_budget_seconds"])
    if not math.isfinite(budget) or budget <= 0 or set(allowed) & set(forbidden):
        raise ValueError("Invalid task budget or overlapping allowed/forbidden paths")
    return Task(path, manifest["task_id"], manifest["suite_version"], manifest["category"], allowed, forbidden,
                budget, verifier, (path / "instruction.md").read_text(encoding="utf-8"))


def _read_tree(root: Path) -> dict[str, bytes]:
    if root.is_symlink() or root.is_junction() or not root.is_dir():
        raise ValueError("Checkpoint root must be an ordinary directory, not a link")
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise ValueError(f"Checkpoint refuses link: {path.name}")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path.read_bytes()
        elif not path.is_dir():
            raise ValueError(f"Unsupported checkpoint entry: {path.name}")
    return files


def _tree_hash(files: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        encoded = name.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


def _write_tree(files: Mapping[str, bytes], destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def prepare_workspace(task: Task, workspace: Path) -> None:
    """Copy public files only; existing workspace must be empty and benchmark-owned."""
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError("Worker workspace must be fresh and empty")
    workspace.mkdir(parents=True, exist_ok=True)
    for name, data in _read_tree(task.path / "seed").items():
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for name in ("instruction.md", "task.json"):
        shutil.copyfile(task.path / name, workspace / name)


@dataclass(frozen=True)
class Snapshot:
    path: Path
    files: Mapping[str, bytes]
    tree_hash: str

    def check_intact(self) -> None:
        if _tree_hash(_read_tree(self.path)) != self.tree_hash:
            raise ValueError("Archived checkpoint changed; refuse evaluation")


def capture(workspace: Path, destination: Path) -> Snapshot:
    """Call only after termination confirmation; never overwrite a checkpoint."""
    if destination.resolve().is_relative_to(workspace.resolve()):
        raise ValueError("Evidence must be outside worker workspace")
    files = _read_tree(workspace)
    _write_tree(files, destination)
    return Snapshot(destination, MappingProxyType(files), _tree_hash(files))


def changed_paths(before: Snapshot, after: Snapshot) -> list[str]:
    return sorted(name for name in before.files.keys() | after.files.keys()
                  if before.files.get(name) != after.files.get(name))


@dataclass(frozen=True)
class Verification:
    status: str
    returncode: int | None
    stdout: str
    stderr: str
    duration_ms: float


def verify(snapshot: Snapshot, verifier: Path, output: Path, *, timeout_seconds: float = 10) -> Verification:
    """Execute the trusted verifier on a disposable copy, never archived S1 itself.

    This is a process boundary for trusted fixtures, not a hostile-code sandbox.
    Timeout kills only the verifier child created by subprocess.run.
    """
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("Verifier timeout must be finite and positive")
    snapshot.check_intact()
    output.mkdir(parents=True, exist_ok=False)
    _write_tree(snapshot.files, output / "workspace")
    start = time.monotonic()
    code = None
    stdout = stderr = ""
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-B", str(verifier.resolve()), str((output / "workspace").resolve())],
            cwd=output, capture_output=True, timeout=timeout_seconds,
        )
        code = completed.returncode
        stdout, stderr = completed.stdout.decode("utf-8", "replace"), completed.stderr.decode("utf-8", "replace")
        status = {0: "passed", 1: "failed"}.get(code, "infrastructure_error")
    except subprocess.TimeoutExpired as error:
        status = "timed_out"
        stdout = (error.stdout or b"").decode("utf-8", "replace")
        stderr = (error.stderr or b"").decode("utf-8", "replace")
    except OSError as error:
        status, stderr = "infrastructure_error", f"Verifier launch failed: {type(error).__name__}"
    duration = (time.monotonic() - start) * 1000
    (output / "stdout.txt").write_text(stdout, encoding="utf-8")
    (output / "stderr.txt").write_text(stderr, encoding="utf-8")
    snapshot.check_intact()
    return Verification(status, code, stdout, stderr, duration)


MUTATION_TOOLS: frozenset[str] = frozenset({"write", "edit", "patch", "delete", "rm", "remove"})
NON_MUTATING_TOOLS: frozenset[str] = frozenset({
    "read", "cat", "view", "grep", "glob", "find", "list", "ls", "browse", "web", "fetch",
})


@dataclass(frozen=True)
class MutationEvent:
    tool: str
    target_path: str
    resolved_path: str
    in_workspace: bool
    in_scope: bool
    status: str
    message_id: str
    call_id: str


@dataclass(frozen=True)
class UnverifiableOperation:
    tool: str
    reason: str
    message_id: str
    call_id: str
    input_summary: dict[str, Any]


@dataclass(frozen=True)
class ScopeAudit:
    snapshot_violations: tuple[str, ...]
    transcript_violations: tuple[str, ...]
    all_violations: tuple[str, ...]
    mutated_paths: tuple[str, ...]
    mutation_events: tuple[MutationEvent, ...]
    unverifiable_operations: tuple[UnverifiableOperation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_violations": list(self.snapshot_violations),
            "transcript_violations": list(self.transcript_violations),
            "all_violations": list(self.all_violations),
            "mutated_paths": list(self.mutated_paths),
            "mutation_events": [asdict(e) for e in self.mutation_events],
            "unverifiable_operations": [asdict(u) for u in self.unverifiable_operations],
        }


def _is_subpath(target: Path, base: Path) -> bool:
    """Check if target is inside base, respecting Windows case-insensitivity and directory boundaries."""
    try:
        t_resolved = target.resolve()
        b_resolved = base.resolve()
    except Exception:
        return False
    try:
        t_resolved.relative_to(b_resolved)
        return True
    except ValueError:
        pass
    if sys.platform == "win32" or platform.system() == "Windows":
        try:
            t_norm = os.path.normcase(os.path.normpath(str(t_resolved)))
            b_norm = os.path.normcase(os.path.normpath(str(b_resolved)))
            return t_norm == b_norm or t_norm.startswith(b_norm + os.sep)
        except Exception:
            return False
    return False


def _relative_to_workspace(target: Path, base: Path) -> str:
    """Get the relative POSIX path of target within base, normalizing Windows casing."""
    t_resolved = target.resolve()
    b_resolved = base.resolve()
    try:
        return t_resolved.relative_to(b_resolved).as_posix()
    except ValueError:
        if sys.platform == "win32" or platform.system() == "Windows":
            t_norm = os.path.normcase(os.path.normpath(str(t_resolved)))
            b_norm = os.path.normcase(os.path.normpath(str(b_resolved)))
            if t_norm.startswith(b_norm + os.sep):
                return t_norm[len(b_norm) + 1:].replace("\\", "/")
            if t_norm == b_norm:
                return "."
        raise


def _matches_any(rel_posix: str, patterns: tuple[str, ...]) -> bool:
    is_win = sys.platform == "win32" or platform.system() == "Windows"
    target = rel_posix.lower() if is_win else rel_posix
    for p in patterns:
        candidate = p.lower() if is_win else p
        if target == candidate:
            return True
    return False


def audit_transcript(
    task: Task, workspace: Path, history: list[dict],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[MutationEvent, ...], tuple[UnverifiableOperation, ...]]:
    workspace_resolved = workspace.resolve()
    mutation_events: list[MutationEvent] = []
    unverifiable_ops: list[UnverifiableOperation] = []
    mutated_paths_set: set[str] = set()
    violations_set: set[str] = set()

    if not isinstance(history, list):
        return ((), (), (), ())

    for msg in history:
        if not isinstance(msg, dict):
            continue
        msg_id = str((msg.get("info") or {}).get("id") or "")
        parts = msg.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict) or part.get("type") != "tool":
                continue
            tool = str(part.get("tool") or "")
            call_id = str(part.get("callID") or "")
            state = part.get("state")
            state_dict = state if isinstance(state, dict) else {}
            status = str(state_dict.get("status") or "")
            inp = state_dict.get("input")
            inp_dict = inp if isinstance(inp, dict) else {}

            if tool in NON_MUTATING_TOOLS:
                continue

            if tool in MUTATION_TOOLS:
                raw_path = (
                    inp_dict.get("filePath")
                    or inp_dict.get("path")
                    or inp_dict.get("file_path")
                    or inp_dict.get("file")
                )
                if not isinstance(raw_path, str) or not raw_path.strip():
                    unverifiable_ops.append(UnverifiableOperation(
                        tool=tool,
                        reason=f"Malformed or missing target path in {tool} tool call",
                        message_id=msg_id,
                        call_id=call_id,
                        input_summary={k: str(v)[:100] for k, v in inp_dict.items()},
                    ))
                    continue

                raw_path_str = raw_path.strip()
                workdir = inp_dict.get("workdir") or inp_dict.get("cwd")
                if isinstance(workdir, str) and workdir.strip():
                    exec_dir = Path(workdir.strip()).resolve()
                else:
                    exec_dir = workspace_resolved

                try:
                    target_p = Path(raw_path_str)
                    resolved_p = target_p.resolve() if target_p.is_absolute() else (exec_dir / target_p).resolve()
                except Exception as exc:
                    unverifiable_ops.append(UnverifiableOperation(
                        tool=tool,
                        reason=f"Failed to resolve target path {raw_path_str!r}: {exc}",
                        message_id=msg_id,
                        call_id=call_id,
                        input_summary={"raw_path": raw_path_str},
                    ))
                    continue

                in_workspace = _is_subpath(resolved_p, workspace_resolved)
                if in_workspace:
                    try:
                        rel = _relative_to_workspace(resolved_p, workspace_resolved)
                    except Exception:
                        rel = resolved_p.name
                    in_scope = _matches_any(rel, task.allowed_paths) and not _matches_any(rel, task.forbidden_paths)
                    canonical_path = rel
                else:
                    in_scope = False
                    canonical_path = str(resolved_p)

                mutated_paths_set.add(canonical_path)

                event = MutationEvent(
                    tool=tool,
                    target_path=raw_path_str,
                    resolved_path=str(resolved_p),
                    in_workspace=in_workspace,
                    in_scope=in_scope,
                    status=status,
                    message_id=msg_id,
                    call_id=call_id,
                )
                mutation_events.append(event)

                if status == "completed" and not in_scope:
                    violations_set.add(canonical_path)

            else:
                cmd = inp_dict.get("command") or inp_dict.get("cmd")
                summary: dict[str, Any] = {}
                if isinstance(cmd, str):
                    summary["command"] = cmd[:120]
                unverifiable_ops.append(UnverifiableOperation(
                    tool=tool,
                    reason=f"Opaque execution tool '{tool}' cannot statically verify filesystem mutations",
                    message_id=msg_id,
                    call_id=call_id,
                    input_summary=summary,
                ))

    return (
        tuple(sorted(violations_set)),
        tuple(sorted(mutated_paths_set)),
        tuple(mutation_events),
        tuple(unverifiable_ops),
    )


def audit_scope(
    task: Task, workspace: Path, s0: Snapshot, s1: Snapshot | None, history: list[dict],
) -> ScopeAudit:
    """Audit S0/S1 workspace diff and transcript tool mutations against task scope."""
    if s1 is not None:
        changed = tuple(changed_paths(s0, s1))
        snapshot_violations = tuple(
            name for name in changed
            if not _matches_any(name, task.allowed_paths) or _matches_any(name, task.forbidden_paths)
        )
    else:
        snapshot_violations = ()

    transcript_violations, mutated_paths, events, unverifiable = audit_transcript(
        task, workspace, history,
    )

    all_violations = tuple(sorted(set(snapshot_violations) | set(transcript_violations)))

    return ScopeAudit(
        snapshot_violations=snapshot_violations,
        transcript_violations=transcript_violations,
        all_violations=all_violations,
        mutated_paths=mutated_paths,
        mutation_events=events,
        unverifiable_operations=unverifiable,
    )


def reaudit_trial(evidence_dir: Path, task: Task) -> ScopeAudit:
    """Traceably audit an existing trial evidence directory without modifying it."""
    evidence_dir = evidence_dir.resolve()
    lifecycle = json.loads((evidence_dir / "lifecycle.json").read_text(encoding="utf-8"))
    workspace = Path(lifecycle["workspace"]["path"])
    s0_tree = _read_tree(evidence_dir / "S0")
    s0 = Snapshot(evidence_dir / "S0", MappingProxyType(s0_tree), _tree_hash(s0_tree))
    s1 = None
    if (evidence_dir / "S1").is_dir():
        s1_tree = _read_tree(evidence_dir / "S1")
        s1 = Snapshot(evidence_dir / "S1", MappingProxyType(s1_tree), _tree_hash(s1_tree))
    history_file = evidence_dir / "session.json"
    history = json.loads(history_file.read_text(encoding="utf-8")) if history_file.is_file() else []
    return audit_scope(task, workspace, s0, s1, history)

