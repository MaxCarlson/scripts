from __future__ import annotations

import json
from pathlib import Path

from runmux.workspace_state import WorkspaceState, WorkspaceStateStore


def test_workspace_state_round_trips_open_full_ids_and_scroll_offsets(tmp_path: Path) -> None:
    state_store = WorkspaceStateStore(tmp_path / "state", tmp_path / "repo", app_id="runmux")
    state = WorkspaceState(
        open_run_ids=["full-run-id-a", "full-run-id-b"],
        active_run_id="full-run-id-b",
        scroll_offsets={"full-run-id-a": 12, "full-run-id-b": 0},
    )

    state_store.save(state)

    assert state_store.load() == state
    assert state_store.path.is_relative_to(tmp_path / "state")


def test_workspace_file_is_scoped_to_canonical_root_and_app(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    root_a = tmp_path / "repo-a"
    root_b = tmp_path / "repo-b"
    root_a.mkdir()
    root_b.mkdir()

    paths = {
        WorkspaceStateStore(state_dir, root_a, app_id="runmux").path,
        WorkspaceStateStore(state_dir, root_a, app_id="other-app").path,
        WorkspaceStateStore(state_dir, root_b, app_id="runmux").path,
    }

    assert len(paths) == 3
    assert all(path.parent == state_dir / "workspaces" for path in paths)


def test_corrupt_or_unknown_schema_state_loads_empty(tmp_path: Path) -> None:
    state_store = WorkspaceStateStore(tmp_path / "state", tmp_path / "repo")
    state_store.path.parent.mkdir(parents=True)
    state_store.path.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")

    assert state_store.load() == WorkspaceState()


def test_workspace_state_never_discovers_historical_run_ids(tmp_path: Path) -> None:
    state_store = WorkspaceStateStore(tmp_path / "state", tmp_path / "repo")
    state_store.save(WorkspaceState())

    assert state_store.load().open_run_ids == []
