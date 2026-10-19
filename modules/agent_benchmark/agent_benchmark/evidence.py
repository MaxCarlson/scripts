"""Byte-exact checkpoints and isolated verification for trusted offline tasks."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import sys
import time
from types import MappingProxyType
from typing import Mapping


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
