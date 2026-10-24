from pathlib import Path

import pytest

import cli_tui.layout_store as layout_store
from cli_tui.layout_store import LayoutError, PaneLayoutStore


def test_layout_store_scopes_by_launch_directory_and_app(tmp_path: Path) -> None:
    store = PaneLayoutStore(tmp_path)
    store.save("C:/workspace/project", "compressor", {"panes": [{"title": "Main"}]})

    assert store.load("C:/workspace/project", "compressor") == {"panes": [{"title": "Main"}]}
    assert store.load("C:/workspace/other", "compressor") is None
    assert store.load("C:/workspace/project", "other-app") is None


def test_layout_store_rejects_corrupt_or_mismatched_data(tmp_path: Path) -> None:
    store = PaneLayoutStore(tmp_path)
    store.save("/workspace/project", "tool", {"panes": []})
    path = store.path_for("/workspace/project", "tool")
    path.write_text('{"schema": 999}', encoding="utf-8")

    with pytest.raises(LayoutError, match="schema"):
        store.load("/workspace/project", "tool")


def test_layout_store_reports_corrupt_json(tmp_path: Path) -> None:
    store = PaneLayoutStore(tmp_path)
    path = store.path_for("/workspace/project", "tool")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(LayoutError, match="corrupt"):
        store.load("/workspace/project", "tool")


def test_layout_store_atomic_replace_preserves_previous_layout_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PaneLayoutStore(tmp_path)
    store.save("/workspace/project", "tool", {"panes": [{"title": "old"}]})
    path = store.path_for("/workspace/project", "tool")
    previous = path.read_text(encoding="utf-8")

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(layout_store.os, "replace", fail_replace)
    with pytest.raises(LayoutError, match="replace failed"):
        store.save("/workspace/project", "tool", {"panes": [{"title": "new"}]})

    assert path.read_text(encoding="utf-8") == previous
    assert list(tmp_path.glob("*.tmp")) == []


def test_layout_store_rejects_non_json_values_before_writing(tmp_path: Path) -> None:
    store = PaneLayoutStore(tmp_path)

    with pytest.raises(LayoutError, match="unsupported values"):
        store.save("/workspace/project", "tool", {"panes": [], "value": float("nan")})

    assert not store.path_for("/workspace/project", "tool").exists()
