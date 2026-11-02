from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent_benchmark.suite_revision import (
    DatasetRevisionError,
    include_registry_resolution,
    resolve_registry_snapshot,
    verify_saved_registry_snapshot,
)

FROZEN_REVISION = "f30b14415dd733c83627204bad0af69a89ceb46f"
TASKS = ["polyglot_python_beer-song", "polyglot_python_bottle-song"]
REPOSITORY = "https://github.com/laude-institute/harbor-datasets.git"


def _resolved(task_ids: list[str], commit: str | None = FROZEN_REVISION) -> list[dict[str, str | None]]:
    return [{"task_id": task, "git_url": REPOSITORY, "git_commit_id": commit} for task in task_ids]


def test_registry_snapshot_verifies_all_selected_tasks_at_the_frozen_revision(tmp_path: Path):
    registry_path = tmp_path / "registry.json"
    registry_bytes = b'{"datasets": [{"name": "aider-polyglot"}]}'

    def resolver(*, registry_path: Path, **_kwargs):
        registry_path.write_bytes(registry_bytes)
        return _resolved(TASKS)

    result = resolve_registry_snapshot(
        dataset="aider-polyglot", task_ids=TASKS, expected_revision=FROZEN_REVISION,
        registry_path=registry_path, resolver=resolver,
    )

    assert result["verified"] is True
    assert result["registry_sha256"] == hashlib.sha256(registry_bytes).hexdigest()
    assert [item["task_id"] for item in result["tasks"]] == TASKS


def test_registry_snapshot_rejects_revision_mismatch_before_run(tmp_path: Path):
    registry_path = tmp_path / "registry.json"

    def resolver(*, registry_path: Path, **_kwargs):
        registry_path.write_text("{}", encoding="utf-8")
        return _resolved(TASKS, "a-different-revision")

    with pytest.raises(DatasetRevisionError, match="revision mismatch"):
        resolve_registry_snapshot(
            dataset="aider-polyglot", task_ids=TASKS, expected_revision=FROZEN_REVISION,
            registry_path=registry_path, resolver=resolver,
        )


@pytest.mark.parametrize("resolved", [None, _resolved(TASKS, None), _resolved([TASKS[0]])])
def test_registry_snapshot_fails_closed_when_revision_cannot_be_established(tmp_path: Path, resolved):
    registry_path = tmp_path / "registry.json"

    def resolver(*, registry_path: Path, **_kwargs):
        registry_path.write_text("{}", encoding="utf-8")
        return resolved

    with pytest.raises(DatasetRevisionError, match="could not establish"):
        resolve_registry_snapshot(
            dataset="aider-polyglot", task_ids=TASKS, expected_revision=FROZEN_REVISION,
            registry_path=registry_path, resolver=resolver,
        )


def test_registry_resolution_failure_is_a_clear_closed_error(tmp_path: Path):
    def resolver(**_kwargs):
        raise RuntimeError("registry unavailable")

    with pytest.raises(DatasetRevisionError, match="no inference was dispatched"):
        resolve_registry_snapshot(
            dataset="aider-polyglot", task_ids=TASKS, expected_revision=FROZEN_REVISION,
            registry_path=tmp_path / "registry.json", resolver=resolver,
        )


def test_saved_registry_snapshot_and_manifest_are_verified_before_dispatch(tmp_path: Path):
    registry_bytes = b'{"verified": true}'
    resolution = {
        "verified": True, "harbor_version": "0.25.0", "registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
        "registry_path": "registry/registry.json", "expected_revision": FROZEN_REVISION,
        "tasks": _resolved(TASKS),
    }
    planned = include_registry_resolution({
        "cohort": "aider-python-10", "source_revision": FROZEN_REVISION, "tasks": TASKS,
        "provenance": {"registry_revision_required": True},
    }, resolution)
    planned.update(run_id="fixture", created_at="fixture")
    registry_path = tmp_path / "registry" / "registry.json"
    registry_path.parent.mkdir()
    registry_path.write_bytes(registry_bytes)

    assert verify_saved_registry_snapshot(tmp_path, planned) == registry_path

    registry_path.write_bytes(b"changed")
    with pytest.raises(DatasetRevisionError, match="snapshot changed"):
        verify_saved_registry_snapshot(tmp_path, planned)

    registry_path.write_bytes(registry_bytes)
    tampered = {**planned, "source_revision": "changed"}
    with pytest.raises(DatasetRevisionError, match="manifest changed"):
        verify_saved_registry_snapshot(tmp_path, tampered)
