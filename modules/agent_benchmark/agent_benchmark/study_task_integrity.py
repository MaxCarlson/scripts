"""Fail-closed identity checks for the pinned specification-verification cohort."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

EXPECTED = {
    "polyglot_python_beer-song": ("79c3e5b6f2300c5de6ff862d212ea38d329ef31eb243e6a55da975c622b53376", "01402f4ff69be049e7bc032c55215b018f19aa129021c3cf59d508764eb3a417"),
    "polyglot_python_bottle-song": ("7aa03a961facf5071aea121fb5ccb1a9519c133230025db0922a70803dab139c", "c3c6d0bdf66833931416f8d9347285950fd895f9e648ebdd9b17c8223c0bdb2b"),
    "polyglot_python_bowling": ("2150b7c876f6ef7f988ec9c032ee4e873aa6e62b9591183a44e6317c64d7104f", "cb919322a81c1733f40d8c60345aa3f164de9d23a9813d2b50d6a6d4027c3790"),
}

_SCRIPT = r'''
import hashlib, importlib.metadata, json, sys
from pathlib import Path
from harbor.models.task.id import GitTaskId
from harbor.publisher.packager import Packager
if importlib.metadata.version('harbor') != '0.25.0':
    raise RuntimeError('Harbor 0.25.0 is required')
results = []
for row in json.loads(sys.argv[1]):
    task = GitTaskId(git_url=row['git_url'], git_commit_id=row['git_commit_id'], path=Path(row['git_path']))
    root = task.get_local_path()
    if not root.is_dir() or not (root / 'tests').is_dir():
        raise RuntimeError('selected Harbor cached task or verifier is missing: ' + row['task_id'])
    task_hash, _ = Packager.compute_content_hash(root)
    digest = hashlib.sha256()
    for p in sorted((root / 'tests').rglob('*')):
        if p.is_symlink(): raise RuntimeError('verifier contains symlink')
        if p.is_file(): digest.update(p.relative_to(root).as_posix().encode() + b'\0' + hashlib.sha256(p.read_bytes()).digest())
    results.append({'task_id': row['task_id'], 'task_sha256': task_hash, 'verifier_sha256': digest.hexdigest()})
print(json.dumps(results))
'''


def verify_study_task_trees(manifest: dict, *, python: str | None = None) -> list[dict]:
    """Hash Harbor's actual cache selection before trial dispatch; never download."""
    interpreter = python or os.environ.get("HARBOR_025_PYTHON")
    if not interpreter or not Path(interpreter).is_file():
        raise ValueError("HARBOR_025_PYTHON must identify the Harbor 0.25.0 interpreter; no inference dispatched")
    resolution = manifest.get("provenance", {}).get("registry_resolution", {})
    rows = resolution.get("tasks", [])
    if (not rows or len(rows) != len(manifest.get("tasks", []))
            or {r.get("task_id") for r in rows} != set(manifest.get("tasks", []))):
        raise ValueError("study registry task set is incomplete; no inference dispatched")
    for row in rows:
        task = row.get("task_id")
        if (task not in EXPECTED or row.get("git_path") != f"datasets/aider_polyglot/{task}"
                or row.get("git_url") != "https://github.com/laude-institute/harbor-datasets.git"
                or row.get("git_commit_id") != "f30b14415dd733c83627204bad0af69a89ceb46f"):
            raise ValueError("study registry task path is unsupported; no inference dispatched")
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", LITELLM_LOCAL_MODEL_COST_MAP="True")
    result = subprocess.run([interpreter, "-B", "-c", _SCRIPT, json.dumps(rows)], env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
    if result.returncode:
        raise ValueError(f"Harbor task identity check failed (exit {result.returncode}); no inference dispatched")
    try:
        actual = json.loads(result.stdout)
        if (not isinstance(actual, list) or len(actual) != len(rows)
                or {x["task_id"] for x in actual} != {r["task_id"] for r in rows}):
            raise ValueError("task set mismatch")
        for row in actual:
            if (row["task_sha256"], row["verifier_sha256"]) != EXPECTED[row["task_id"]]:
                raise ValueError("task or verifier digest mismatch")
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Harbor task identity check failed: {error}; no inference dispatched") from error
    return actual
