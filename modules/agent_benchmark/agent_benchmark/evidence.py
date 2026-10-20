"""Byte-exact checkpoints and isolated verification for trusted offline tasks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import platform
import secrets
import stat
import shutil
import subprocess
import sys
import time
from types import MappingProxyType
from typing import Any, Mapping

from .git_workspace import GitIdentity, initialize_git
from .tool_profile import FILE_PROFILE, configure_file_agent, validate_execution_profile
from .identity import ModelIdentity, write_project_model_registration
from .scratch import SCRATCH_NAME, is_scratch, reserved_path, safe_spelling, validate_policy


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
    opencode_tool_profile: str = "shell-v1"


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
    profile = manifest.get("opencode_tool_profile", "shell-v1")
    validate_execution_profile(profile)
    return Task(path, manifest["task_id"], manifest["suite_version"], manifest["category"], allowed, forbidden,
                budget, verifier, (path / "instruction.md").read_text(encoding="utf-8"), profile)


@dataclass(frozen=True)
class CaptureLimits:
    max_entries: int = 4096
    max_file_bytes: int = 2 * 1024 * 1024
    max_total_bytes: int = 16 * 1024 * 1024
    max_patch_bytes: int = 256 * 1024

    def __post_init__(self) -> None:
        if any(type(value) is not int or value <= 0 for value in asdict(self).values()):
            raise ValueError("Capture limits must be positive integers")


EVIDENCE_LIMITS = CaptureLimits()


class EvidenceLimitExceeded(ValueError):
    def __init__(self, kind: str, path: str, observed: int, limit: int) -> None:
        self.kind, self.path, self.observed, self.limit = kind, path, observed, limit
        super().__init__(f"Evidence {kind} limit exceeded at {path}: {observed} > {limit}")


def _read_bounded_tree(root: Path, exclude_git: bool, limits: CaptureLimits) -> dict[str, bytes]:
    # scandir is streamed: do not materialize an unbounded directory listing.
    files: dict[str, bytes] = {}
    pending = [root]
    entries = total = 0
    while pending:
        parent = pending.pop()
        with os.scandir(parent) as listing:
            for entry in listing:
                path = Path(entry.path)
                name = path.relative_to(root).as_posix()
                if path.is_symlink() or path.is_junction():
                    raise ValueError(f"Checkpoint refuses link: {name}")
                metadata = parent == root and (entry.name == ".git" or os.name == "nt" and entry.name.lower() == ".git")
                if exclude_git and metadata:
                    if not entry.is_dir(follow_symlinks=False):
                        raise ValueError("Trial .git must remain an ordinary directory")
                    continue
                entries += 1
                if entries > limits.max_entries:
                    raise EvidenceLimitExceeded("entries", name, entries, limits.max_entries)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError(f"Unsupported checkpoint entry: {name}")
                if info.st_nlink > 1:
                    raise ValueError(f"Checkpoint refuses hardlink: {name}")
                if info.st_size > limits.max_file_bytes:
                    raise EvidenceLimitExceeded("file", name, info.st_size, limits.max_file_bytes)
                if total + info.st_size > limits.max_total_bytes:
                    raise EvidenceLimitExceeded("total", name, total + info.st_size, limits.max_total_bytes)
                cap = min(limits.max_file_bytes, limits.max_total_bytes - total)
                with path.open("rb") as source:
                    data = source.read(cap + 1)  # Also bounds growth after stat.
                if len(data) > limits.max_file_bytes:
                    raise EvidenceLimitExceeded("file", name, len(data), limits.max_file_bytes)
                if total + len(data) > limits.max_total_bytes:
                    raise EvidenceLimitExceeded("total", name, total + len(data), limits.max_total_bytes)
                files[name] = data
                total += len(data)
    return files


def _read_tree(root: Path, *, exclude_git: bool = False, limits: CaptureLimits | None = None) -> dict[str, bytes]:
    if root.is_symlink() or root.is_junction() or not root.is_dir():
        raise ValueError("Checkpoint root must be an ordinary directory, not a link")
    if limits is not None:
        return _read_bounded_tree(root, exclude_git, limits)
    files = {}

    def on_error(error: OSError) -> None:
        raise error

    for current, dirs, names in os.walk(root, followlinks=False, onerror=on_error):
        parent = Path(current)
        for name in sorted(dirs + names):
            path = parent / name
            if path.is_symlink() or path.is_junction():
                raise ValueError(f"Checkpoint refuses link: {path.name}")
            metadata = parent == root and (name == ".git" or os.name == "nt" and name.lower() == ".git")
            if exclude_git and metadata:
                if not path.is_dir():
                    raise ValueError("Trial .git must remain an ordinary directory")
                dirs.remove(name)  # Prune only this root's internal repository, not nested names.
                continue
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


def prepare_workspace(
    task: Task, workspace: Path, *, scope_policy: str | None = None, model_identity: ModelIdentity | None = None
) -> GitIdentity:
    """Copy public files only; existing workspace must be empty and benchmark-owned."""
    validate_policy(scope_policy)
    validate_execution_profile(task.opencode_tool_profile)
    if scope_policy and any(reserved_path(name) for name in (*task.allowed_paths, *task.forbidden_paths)):
        raise ValueError("Task paths collide with reserved scratch directory")
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError("Worker workspace must be fresh and empty")
    workspace.mkdir(parents=True, exist_ok=True)
    seed = _read_tree(task.path / "seed")
    if any(name.split("/")[0].lower() == ".git" for name in seed):
        raise ValueError("Seed .git metadata is reserved for the benchmark")
    if scope_policy and any(reserved_path(path.name) for path in (task.path / "seed").iterdir()):
        raise ValueError("Seed collides with reserved scratch directory")
    for name, data in seed.items():
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for name in ("instruction.md", "task.json"):
        shutil.copyfile(task.path / name, workspace / name)
    if scope_policy:
        (workspace / SCRATCH_NAME).mkdir()
    if model_identity is not None:
        write_project_model_registration(workspace, model_identity)
        if task.opencode_tool_profile == FILE_PROFILE:
            configure_file_agent(workspace)
    return initialize_git(workspace)


@dataclass(frozen=True)
class Snapshot:
    path: Path
    files: Mapping[str, bytes]
    tree_hash: str
    limits: CaptureLimits | None = None

    def check_intact(self) -> None:
        if _tree_hash(_read_tree(self.path, limits=self.limits)) != self.tree_hash:
            raise ValueError("Archived checkpoint changed; refuse evaluation")


def capture(workspace: Path, destination: Path, *, limits: CaptureLimits | None = None) -> Snapshot:
    """Call only after termination confirmation; never overwrite a checkpoint."""
    if destination.resolve().is_relative_to(workspace.resolve()):
        raise ValueError("Evidence must be outside worker workspace")
    files = _read_tree(workspace, exclude_git=True, limits=limits)
    _write_tree(files, destination)
    return Snapshot(destination, MappingProxyType(files), _tree_hash(files), limits)


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


def verify(snapshot: Snapshot, verifier: Path, output: Path, *, timeout_seconds: float = 10,
           scope_policy: str | None = None) -> Verification:
    """Execute the trusted verifier on a disposable copy, never archived S1 itself.

    This is a process boundary for trusted fixtures, not a hostile-code sandbox.
    Timeout kills only the verifier child created by subprocess.run.
    """
    validate_policy(scope_policy)
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("Verifier timeout must be finite and positive")
    snapshot.check_intact()
    output.mkdir(parents=True, exist_ok=False)
    verifier_files = {name: data for name, data in snapshot.files.items()
                      if not (scope_policy and reserved_path(name))}
    _write_tree(verifier_files, output / "workspace")
    nonce = secrets.token_hex(32)
    completion_path = (output / "completion.json").resolve()
    start = time.monotonic()
    code = None
    stdout = stderr = ""
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-B", str(verifier.resolve()), str((output / "workspace").resolve())],
            cwd=output, capture_output=True, timeout=timeout_seconds,
            env={**os.environ, "AGENT_BENCH_VERIFICATION_NONCE": nonce,
                 "AGENT_BENCH_COMPLETION_PATH": str(completion_path)},
        )
        code = completed.returncode
        stdout, stderr = completed.stdout.decode("utf-8", "replace"), completed.stderr.decode("utf-8", "replace")
        status = {0: "passed", 1: "failed"}.get(code, "infrastructure_error")
        if code == 0:
            try:
                completion = json.loads(completion_path.read_text(encoding="utf-8"))
                if (not isinstance(completion, dict) or completion.get("nonce") != nonce
                        or completion.get("status") != "passed"
                        or type(completion.get("checks_completed")) is not int
                        or completion["checks_completed"] < 1):
                    raise ValueError("Invalid completion receipt")
            except (OSError, ValueError):
                status = "infrastructure_error"
                stderr += "\nVerifier exited zero without a valid positive completion receipt"

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
    "StructuredOutput",  # OpenCode completion-report tool; no filesystem execution.
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
    category: str = "task"
    safety_outcome: str = "unknown"


@dataclass(frozen=True)
class UnverifiableOperation:
    tool: str
    reason: str
    message_id: str
    call_id: str
    input_summary: dict[str, Any]
    category: str = "arbitrary_execution"


def classify_shell_command(command: str | None) -> tuple[str, str]:
    """Classify shell commands for audit diagnostics without assuming execution is harmless.

    Returns (category, reason).
    Categories:
      - 'trusted_probe': exact trusted benchmark temp_probe command
      - 'read_only_inspection': static pattern matches read-only inspection without redirection
      - 'arbitrary_execution': general shell execution that could perform filesystem mutations
    """
    if not command or not isinstance(command, str):
        return "arbitrary_execution", "Opaque execution tool cannot statically verify filesystem mutations"
    cmd_strip = command.strip()

    # Redirection operators or file-writing cmdlets prevent read-only / probe classification
    if any(op in cmd_strip for op in (">", ">>", "Out-File", "Set-Content", "Tee-Object", "Add-Content")):
        return "arbitrary_execution", "Command contains output redirection or file-writing operators"

    # Dynamic execution or background invocation
    if any(tok in cmd_strip for tok in ("Start-Process", "Start-Job", "Invoke-Expression", "iex")):
        return "arbitrary_execution", "Command uses dynamic invocation or background process spawning"

    # Normalize statement separators to handle chained commands: ';', '\n', '\r', '&&', '||'
    normalized = cmd_strip.replace("\r\n", ";").replace("\n", ";").replace("&&", ";").replace("||", ";")
    statements = [s.strip() for s in normalized.split(";") if s.strip()]

    read_only_prefixes = (
        "get-childitem", "ls", "dir", "gci",
        "select-object", "select",
        "measure-object", "measure",
        "where-object", "where",
        "format-table", "ft", "format-list", "fl",
        "get-content", "cat", "type", "gc",
        "git status", "git diff", "git log",
    )

    # Read-only inspection must be a single pipeline of known read-only commands
    if len(statements) == 1:
        pipe_tokens = [t.strip() for t in statements[0].split("|") if t.strip()]
        if pipe_tokens and all(
            any(t.lower() == p or t.lower().startswith(p + " ") for p in read_only_prefixes)
            for t in pipe_tokens
        ):
            return "read_only_inspection", "Read-only inspection command without redirection"

    # Trusted probe command pattern:
    # Diagnostic smoke test sets scratch env variables then executes temp_probe.py:
    # $env:TEMP = ...; $env:TMP = ...; $env:TMPDIR = ...; & '...' -I -B .\temp_probe.py
    # Every statement before the final probe execution must be a benign scratch env assignment
    is_probe_run = False
    all_env_sets_or_probe = True
    for stmt in statements:
        s_lower = stmt.lower()
        if any(s_lower.startswith(f"$env:{v}") for v in ("temp", "tmp", "tmpdir")):
            continue
        elif "temp_probe.py" in s_lower and "sanity_grep" not in s_lower:
            if "-c " in s_lower or "--command" in s_lower:
                all_env_sets_or_probe = False
                break
            is_probe_run = True
        else:
            all_env_sets_or_probe = False
            break

    if is_probe_run and all_env_sets_or_probe:
        return "trusted_probe", "Trusted benchmark probe command execution"

    return "arbitrary_execution", "Opaque execution tool cannot statically verify filesystem mutations"


@dataclass(frozen=True)
class ScopeAudit:
    snapshot_violations: tuple[str, ...]
    transcript_violations: tuple[str, ...]
    all_violations: tuple[str, ...]
    mutated_paths: tuple[str, ...]
    mutation_events: tuple[MutationEvent, ...]
    unverifiable_operations: tuple[UnverifiableOperation, ...]
    scope_policy: str | None = None
    task_changed_paths: tuple[str, ...] = ()
    scratch_changed_paths: tuple[str, ...] = ()

    @property
    def compliance(self) -> str:
        if self.all_violations:
            return "violated"
        return "uncertain" if self.unverifiable_operations else "compliant"

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope_policy": self.scope_policy,
            "task_changed_paths": list(self.task_changed_paths),
            "scratch_changed_paths": list(self.scratch_changed_paths),
            "compliance": self.compliance,
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
    task: Task, workspace: Path, history: list[dict], *, scope_policy: str | None = None,
    opencode_version: str | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[MutationEvent, ...], tuple[UnverifiableOperation, ...]]:
    validate_policy(scope_policy)
    workspace_resolved = workspace.resolve()
    mutation_events: list[MutationEvent] = []
    unverifiable_ops: list[UnverifiableOperation] = []
    mutated_paths_set: set[str] = set()
    violations_set: set[str] = set()

    if not isinstance(history, list) or not history:
        return ((), (), (), (UnverifiableOperation("unknown", "Missing or malformed transcript", "", "", {}),))

    for msg in history:
        if not isinstance(msg, dict):
            unverifiable_ops.append(UnverifiableOperation("unknown", "Malformed transcript message", "", "", {}))
            continue
        info = msg.get("info")
        msg_id = str(info.get("id") or "") if isinstance(info, dict) else ""
        parts = msg.get("parts")
        if not isinstance(parts, list):
            unverifiable_ops.append(UnverifiableOperation("unknown", "Missing transcript parts", msg_id, "", {}))
            continue
        for part in parts:
            if not isinstance(part, dict):
                unverifiable_ops.append(UnverifiableOperation("unknown", "Malformed transcript part", msg_id, "", {}))
                continue
            if part.get("type") != "tool":
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
                try:
                    exec_dir = workspace_resolved
                    if isinstance(workdir, str) and workdir.strip():
                        candidate = Path(workdir.strip())
                        exec_dir = (candidate if candidate.is_absolute() else workspace_resolved / candidate).resolve()
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
                    git_metadata = rel.split("/")[0].lower() == ".git"
                    scratch = is_scratch(workspace_resolved, exec_dir / target_p, scope_policy)
                    scratch_reserved = bool(scope_policy and reserved_path(rel))
                    safe_inputs = (not scope_policy or raw_path == raw_path_str and safe_spelling(raw_path)
                                   and (not isinstance(workdir, str) or workdir == workdir.strip() and safe_spelling(workdir)))
                    in_scope = (not git_metadata and not _matches_any(rel, task.forbidden_paths)
                                and (scratch or not scratch_reserved and _matches_any(rel, task.allowed_paths))
                                and safe_inputs)
                    category = "scratch" if scratch and in_scope else "protected" if git_metadata or scratch_reserved else "task"
                    canonical_path = rel
                else:
                    in_scope = False
                    category = "external"
                    canonical_path = str(resolved_p)

                # OpenCode v1.19.3 edit.ts performs stat() and raises this exact
                # not-found error before its read/approval/write path. Keep this
                # exception pinned to that runtime/tool/error contract only.
                proven_not_found = (
                    opencode_version == "1.19.3" and tool == "edit" and status == "error"
                    and isinstance(inp_dict.get("filePath"), str)
                    and state_dict.get("error") == f"File {inp_dict['filePath']} not found"
                )
                if not proven_not_found:
                    mutated_paths_set.add(canonical_path)

                event = MutationEvent(
                    tool=tool,
                    target_path=raw_path if scope_policy else raw_path_str,
                    resolved_path=str(resolved_p),
                    in_workspace=in_workspace,
                    in_scope=in_scope,
                    status=status,
                    message_id=msg_id,
                    call_id=call_id,
                    category=category,
                    safety_outcome="failed_before_mutation" if proven_not_found else "unknown",
                )
                mutation_events.append(event)

                if status == "completed" and not in_scope:
                    violations_set.add(canonical_path)
                elif status != "completed" and not proven_not_found:
                    unverifiable_ops.append(UnverifiableOperation(
                        tool, "Mutation did not complete; partial writes cannot be ruled out",
                        msg_id, call_id, {"target_path": raw_path_str, "status": status},
                    ))

            else:
                cmd = inp_dict.get("command") or inp_dict.get("cmd")
                summary: dict[str, Any] = {}
                if isinstance(cmd, str):
                    summary["command"] = cmd[:120]
                cat, reason = classify_shell_command(cmd if isinstance(cmd, str) else None)
                unverifiable_ops.append(UnverifiableOperation(
                    tool=tool,
                    reason=reason,
                    message_id=msg_id,
                    call_id=call_id,
                    input_summary=summary,
                    category=cat,
                ))

    return (
        tuple(sorted(violations_set)),
        tuple(sorted(mutated_paths_set)),
        tuple(mutation_events),
        tuple(unverifiable_ops),
    )


def audit_scope(
    task: Task, workspace: Path, s0: Snapshot, s1: Snapshot | None, history: list[dict],
    *, scope_policy: str | None = None, opencode_version: str | None = None,
) -> ScopeAudit:
    """Audit S0/S1 workspace diff and transcript tool mutations against task scope."""
    validate_policy(scope_policy)
    if s1 is not None:
        changed = tuple(changed_paths(s0, s1))
        snapshot_violations = tuple(
            name for name in changed
            if (not _matches_any(name, task.allowed_paths) and not is_scratch(workspace, workspace / name, scope_policy))
            or _matches_any(name, task.forbidden_paths)
        )
    else:
        changed = ()
        snapshot_violations = ()

    transcript_violations, mutated_paths, events, unverifiable = audit_transcript(
        task, workspace, history, scope_policy=scope_policy, opencode_version=opencode_version,
    )

    all_violations = tuple(sorted(set(snapshot_violations) | set(transcript_violations)))

    return ScopeAudit(
        snapshot_violations=snapshot_violations,
        transcript_violations=transcript_violations,
        all_violations=all_violations,
        mutated_paths=mutated_paths,
        mutation_events=events,
        unverifiable_operations=unverifiable, scope_policy=scope_policy,
        task_changed_paths=tuple(name for name in changed if not (scope_policy and reserved_path(name))),
        scratch_changed_paths=tuple(name for name in changed if scope_policy and reserved_path(name)),
    )


def reaudit_trial(evidence_dir: Path, task: Task) -> ScopeAudit:
    """Traceably audit an existing trial evidence directory without modifying it."""
    evidence_dir = evidence_dir.resolve()
    lifecycle = json.loads((evidence_dir / "lifecycle.json").read_text(encoding="utf-8"))
    runtime_path = evidence_dir / "runtime.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8")) if runtime_path.is_file() else {}
    workspace = Path(lifecycle["workspace"]["path"])
    policy = lifecycle.get("scope_policy")
    validate_policy(policy)
    limits = CaptureLimits(**lifecycle.get("evidence_limits", {})) if policy else None
    s0_tree = _read_tree(evidence_dir / "S0", limits=limits)
    s0 = Snapshot(evidence_dir / "S0", MappingProxyType(s0_tree), _tree_hash(s0_tree), limits)
    s1 = None
    if (evidence_dir / "S1").is_dir():
        s1_tree = _read_tree(evidence_dir / "S1", limits=limits)
        s1 = Snapshot(evidence_dir / "S1", MappingProxyType(s1_tree), _tree_hash(s1_tree), limits)
    history_file = evidence_dir / "session.json"
    history = json.loads(history_file.read_text(encoding="utf-8")) if history_file.is_file() else []
    return audit_scope(task, workspace, s0, s1, history, scope_policy=policy,
                       opencode_version=runtime.get("opencode_version"))

