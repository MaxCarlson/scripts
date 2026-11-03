"""Pre-dispatch revision verification using Harbor's registry resolver."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any, Callable

FROZEN_TASK_REPOSITORY = "https://github.com/laude-institute/harbor-datasets.git"
HARBOR_VERSION = "0.25.0"


class DatasetRevisionError(RuntimeError):
    """The selected Harbor registry entries cannot establish the pinned source revision."""


_HARBOR_RESOLVE_SCRIPT = r'''
import asyncio
import importlib.metadata
import json
import sys
from pathlib import Path

import httpx
from harbor.constants import DEFAULT_REGISTRY_URL
from harbor.models.job.config import DatasetConfig

if importlib.metadata.version("harbor") != "0.25.0":
    raise RuntimeError("suite revision resolver requires Harbor 0.25.0")

registry_path = Path(sys.argv[1])
dataset = sys.argv[2]
task_ids = json.loads(sys.argv[3])
response = httpx.get(DEFAULT_REGISTRY_URL, timeout=30.0, follow_redirects=False)
response.raise_for_status()
registry_path.parent.mkdir(parents=True, exist_ok=True)
registry_path.write_bytes(response.content)

async def resolve():
    config = DatasetConfig(name=dataset, task_names=task_ids, registry_path=registry_path)
    configs = await config.get_task_configs()
    return [{
        "task_id": task.path.name if task.path is not None else None,
        "git_path": task.path.as_posix() if task.path is not None else None,
        "git_url": task.git_url,
        "git_commit_id": task.git_commit_id,
    } for task in configs]

print(json.dumps({
    "registry_url": DEFAULT_REGISTRY_URL,
    "tasks": asyncio.run(resolve()),
}))
'''


def _default_harbor_resolver(*, dataset: str, task_ids: list[str], registry_path: Path,
                             expected_revision: str) -> dict[str, Any]:
    del expected_revision  # The Harbor resolver returns the authoritative task commit IDs.
    command: list[str]
    try:
        installed_version = importlib.metadata.version("harbor") if importlib.util.find_spec("harbor") else None
    except importlib.metadata.PackageNotFoundError:
        installed_version = None
    if installed_version == HARBOR_VERSION:
        command = [sys.executable, "-c", _HARBOR_RESOLVE_SCRIPT,
                   str(registry_path), dataset, json.dumps(task_ids)]
    elif shutil.which("uv"):
        command = [shutil.which("uv") or "uv", "tool", "run", "--from", f"harbor=={HARBOR_VERSION}",
                   "python", "-c", _HARBOR_RESOLVE_SCRIPT,
                   str(registry_path), dataset, json.dumps(task_ids)]
    else:
        raise DatasetRevisionError(
            "Harbor 0.25.0's registry resolver is unavailable (need Harbor 0.25.0 in Python or uv); "
            "no inference was dispatched"
        )
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DatasetRevisionError(
            f"Harbor registry resolution could not run: {type(error).__name__}; no inference was dispatched"
        ) from error
    if result.returncode:
        detail = result.stderr.strip().splitlines()[-1:] or result.stdout.strip().splitlines()[-1:]
        reason = detail[0][:500] if detail else f"resolver exit code {result.returncode}"
        raise DatasetRevisionError(f"Harbor registry resolution failed: {reason}; no inference was dispatched")
    try:
        payload = json.loads(result.stdout.splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as error:
        raise DatasetRevisionError(
            "Harbor registry resolver returned unverifiable output; no inference was dispatched"
        ) from error
    return payload


def resolve_registry_snapshot(
    *, dataset: str, task_ids: list[str], expected_revision: str, registry_path: Path,
    resolver: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Resolve task commits with Harbor 0.25.0 against a saved registry snapshot."""
    path = Path(registry_path)
    active_resolver = resolver or _default_harbor_resolver
    try:
        payload = active_resolver(dataset=dataset, task_ids=task_ids, expected_revision=expected_revision,
                                  registry_path=path)
    except DatasetRevisionError:
        raise
    except Exception as error:
        raise DatasetRevisionError(
            f"Harbor registry resolution is unavailable ({type(error).__name__}); no inference was dispatched"
        ) from error
    if not path.is_file():
        raise DatasetRevisionError("Harbor did not save a registry snapshot; no inference was dispatched")
    if isinstance(payload, dict):
        rows = payload.get("tasks")
        source_url = payload.get("registry_url")
    else:
        rows = payload
        source_url = None
    if not isinstance(rows, list):
        raise DatasetRevisionError("could not establish Harbor registry task entries; no inference was dispatched")
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("task_id"), str):
            indexed[row["task_id"]] = row
    if set(indexed) != set(task_ids) or len(rows) != len(task_ids):
        raise DatasetRevisionError(
            "could not establish the exact selected Harbor task set; no inference was dispatched"
        )
    verified_rows: list[dict[str, Any]] = []
    for task_id in task_ids:
        row = indexed[task_id]
        commit = row.get("git_commit_id")
        git_url = row.get("git_url")
        if not isinstance(commit, str) or not commit or not isinstance(git_url, str) or not git_url:
            raise DatasetRevisionError(
                f"could not establish a Git URL/commit for {task_id}; no inference was dispatched"
            )
        if commit != expected_revision:
            raise DatasetRevisionError(
                f"Harbor registry revision mismatch for {task_id}: expected {expected_revision}, "
                f"resolved {commit}; no inference was dispatched"
            )
        if git_url.rstrip("/").removesuffix(".git") != FROZEN_TASK_REPOSITORY.removesuffix(".git"):
            raise DatasetRevisionError(
                f"Harbor registry task {task_id} resolved from unexpected repository {git_url!r}; "
                "no inference was dispatched"
            )
        verified_row = {"task_id": task_id, "git_url": git_url, "git_commit_id": commit}
        if isinstance(row.get("git_path"), str):
            verified_row["git_path"] = row["git_path"]
        verified_rows.append(verified_row)
    return {
        "verified": True,
        "harbor_version": HARBOR_VERSION,
        "registry_url": source_url,
        "registry_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "registry_path": "registry/registry.json",
        "expected_revision": expected_revision,
        "tasks": verified_rows,
    }


def resolve_frozen_registry_snapshot(*, dataset: str, task_ids: list[str], expected_revision: str,
                                     resolver: Callable[..., Any] | None = None) -> tuple[bytes, dict[str, Any]]:
    """Return registry bytes plus Harbor-verified task identity for a run manifest."""
    with TemporaryDirectory(prefix="agent-bench-registry-") as temporary:
        snapshot_path = Path(temporary) / "registry.json"
        result = resolve_registry_snapshot(dataset=dataset, task_ids=task_ids,
                                           expected_revision=expected_revision,
                                           registry_path=snapshot_path, resolver=resolver)
        return snapshot_path.read_bytes(), result


def include_registry_resolution(manifest: dict[str, Any], resolution: dict[str, Any]) -> dict[str, Any]:
    """Bind the resolver evidence and snapshot digest into the immutable run manifest."""
    updated = dict(manifest)
    updated["provenance"] = {**manifest["provenance"], "registry_resolution": resolution}
    updated.pop("manifest_sha256", None)
    digest = json.dumps(updated, sort_keys=True, separators=(",", ":")).encode()
    updated["manifest_sha256"] = hashlib.sha256(digest).hexdigest()
    return updated


def verify_saved_registry_snapshot(run_dir: Path, manifest: dict[str, Any]) -> Path | None:
    """Verify the immutable local registry copy before any measured task dispatch."""
    resolution = manifest.get("provenance", {}).get("registry_resolution")
    if resolution is None:
        revision_required = manifest.get("provenance", {}).get("registry_revision_required")
        if revision_required or manifest.get("cohort") == "aider-python-10":
            raise DatasetRevisionError("frozen cohort has no pre-dispatch registry resolution; no inference was dispatched")
        return None
    digest_payload = {
        key: value for key, value in manifest.items()
        if key not in {"manifest_sha256", "run_id", "created_at"}
    }
    actual_manifest_digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if actual_manifest_digest != manifest.get("manifest_sha256"):
        raise DatasetRevisionError("run manifest changed after registry verification; no inference was dispatched")
    if resolution.get("verified") is not True or resolution.get("harbor_version") != HARBOR_VERSION:
        raise DatasetRevisionError("saved Harbor registry verification is incomplete; no inference was dispatched")
    relative = resolution.get("registry_path")
    expected_digest = resolution.get("registry_sha256")
    if not isinstance(relative, str) or not isinstance(expected_digest, str):
        raise DatasetRevisionError("saved registry provenance is incomplete; no inference was dispatched")
    path = (Path(run_dir) / relative).resolve()
    if not path.is_relative_to(Path(run_dir).resolve()) or not path.is_file():
        raise DatasetRevisionError("saved Harbor registry snapshot is missing; no inference was dispatched")
    actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_digest != expected_digest:
        raise DatasetRevisionError("saved Harbor registry snapshot changed; no inference was dispatched")
    expected_revision = manifest.get("source_revision")
    if resolution.get("expected_revision") != expected_revision:
        raise DatasetRevisionError("saved Harbor registry revision does not match the run manifest; no inference was dispatched")
    rows = resolution.get("tasks")
    task_ids = manifest.get("tasks")
    if not isinstance(rows, list) or not isinstance(task_ids, list):
        raise DatasetRevisionError("saved Harbor registry task resolution is incomplete; no inference was dispatched")
    by_id = {row.get("task_id"): row for row in rows if isinstance(row, dict)}
    expected_repository = FROZEN_TASK_REPOSITORY.removesuffix(".git")
    if set(by_id) != set(task_ids):
        raise DatasetRevisionError("saved Harbor registry resolution does not match the frozen cohort; no inference was dispatched")
    for task in task_ids:
        row = by_id[task]
        git_url = row.get("git_url")
        if (row.get("git_commit_id") != expected_revision or not isinstance(git_url, str)
                or git_url.rstrip("/").removesuffix(".git") != expected_repository):
            raise DatasetRevisionError(
                "saved Harbor registry resolution does not match the frozen cohort; no inference was dispatched"
            )
    return path
