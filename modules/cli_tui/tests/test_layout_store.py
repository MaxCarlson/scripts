from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli_tui.layout_store import LayoutError, PaneLayoutStore, normalize_launch_dir


def test_layout_store_round_trips_and_is_scoped_by_directory_and_app(
    tmp_path: Path,
) -> None:
    store = PaneLayoutStore(
        tmp_path, launch_dir=str(tmp_path / "project"), app_id="manga"
    )
    payload = {"panes": [{"title": "Main", "type": "command"}], "active_index": 0}

    store.save(payload)

    assert store.load() == payload
    assert (
        store.path
        != PaneLayoutStore(
            tmp_path, launch_dir=str(tmp_path / "other"), app_id="manga"
        ).path
    )
    assert (
        store.path
        != PaneLayoutStore(
            tmp_path, launch_dir=str(tmp_path / "project"), app_id="other"
        ).path
    )


def test_layout_store_rejects_identity_mismatch_and_unsupported_schema(
    tmp_path: Path,
) -> None:
    store = PaneLayoutStore(tmp_path, launch_dir=str(tmp_path), app_id="tool")
    store.save({"panes": [], "active_index": 0})
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    raw["identity"]["app_id"] = "different"
    store.path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(LayoutError, match="identity"):
        store.load()

    raw["identity"]["app_id"] = "tool"
    raw["schema_version"] = 999
    store.path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(LayoutError, match="schema"):
        store.load()


def test_layout_store_reports_corrupt_json_and_does_not_leave_temp_files(
    tmp_path: Path,
) -> None:
    store = PaneLayoutStore(tmp_path, launch_dir=str(tmp_path), app_id="tool")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{broken", encoding="utf-8")

    with pytest.raises(LayoutError, match="JSON"):
        store.load()

    store.save({"panes": [], "active_index": 0})
    assert list(store.path.parent.glob("*.tmp")) == []


def test_normalize_launch_dir_resolves_relative_segments(tmp_path: Path) -> None:
    path = tmp_path / "project"
    path.mkdir()

    assert normalize_launch_dir(str(path / ".")) == normalize_launch_dir(str(path))
