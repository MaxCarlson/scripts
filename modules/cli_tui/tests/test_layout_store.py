from pathlib import Path

from cli_tui.layout_store import PaneLayoutStore


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

    assert store.load("/workspace/project", "tool") is None
