from pathlib import Path

from mangadl.models import InputUrl
from mangadl.partial_reconcile import partial_key
from mangadl.partial_ui import (
    PartialInteractiveList,
    PartialTree,
    build_partial_inventory,
    partial_details,
)
from mangadl.state import StateStore


def test_inventory_recovers_legacy_url_and_recursive_size(tmp_path: Path) -> None:
    destination = tmp_path / "library"
    url = "https://example.test/gallery/one"
    state = StateStore(destination / ".mangadl" / "state.sqlite3")
    try:
        run_id = state.create_run({"test": True})
        state.add_jobs(run_id, [InputUrl(url, url, "test", 1)], {url: "gallery-dl"})
    finally:
        state.close()
    owner = destination / "_partial" / partial_key(url)
    nested = owner / "site" / "gallery"
    nested.mkdir(parents=True)
    (nested / "001.jpg").write_bytes(b"12345")

    partial_root, entries, sizes = build_partial_inventory(destination)

    assert partial_root == destination / "_partial"
    assert len(entries) == 1
    assert entries[0].url == url
    assert entries[0].ownership == "legacy; URL recovered from state"
    assert (entries[0].files, entries[0].size) == (1, 5)
    assert sizes[owner] == (1, 5)
    assert f"URL: {url}" in partial_details(entries[0])


def test_partial_tree_expands_and_sorts_hierarchically(tmp_path: Path) -> None:
    destination = tmp_path / "library"
    first = destination / "_partial" / "first"
    second = destination / "_partial" / "second"
    (first / "z-child").mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "z-child" / "001.jpg").write_bytes(b"12345")
    (second / "001.jpg").write_bytes(b"1")
    _root, entries, sizes = build_partial_inventory(destination)
    tree = PartialTree(entries, sizes)
    first_entry = next(entry for entry in entries if entry.name == "first")

    tree.toggle(first_entry)
    visible = tree.visible("size", True)

    assert [entry.name for entry in visible[:2]] == ["first", "z-child"]
    assert visible[1].depth == 1
    tree.toggle(first_entry)
    assert [entry.name for entry in tree.visible("name", False)] == ["first", "second"]


def test_partial_interactive_list_selection_and_deletion(tmp_path: Path) -> None:
    destination = tmp_path / "library"
    owner1 = destination / "_partial" / "owner1"
    owner2 = destination / "_partial" / "owner2"
    child = owner1 / "child_album"
    child.mkdir(parents=True)
    owner2.mkdir(parents=True)
    (child / "001.jpg").write_bytes(b"12345")
    (owner2 / "001.jpg").write_bytes(b"12")

    _root, entries, sizes = build_partial_inventory(destination)
    tree = PartialTree(entries, sizes)
    owner1_entry = next(e for e in entries if e.name == "owner1")
    tree.toggle(owner1_entry)
    visible = tree.visible("size", True)
    assert len(visible) == 3

    list_view = PartialInteractiveList(
        items=visible,
        sorters={"size": lambda e: e.size, "name": lambda e: e.name},
        formatter=lambda *args: "line",
        filter_func=lambda *args: True,
        initial_sort="size",
        initial_order="desc",
        multi_select=True,
        render_checkbox=True,
        enable_delete=True,
        files_extractor=lambda e: e.files,
        size_extractor=lambda e: e.size,
        item_key_func=lambda e: str(e.path),
    )

    child_entry = next(e for e in visible if e.depth > 0)
    assert list_view._render_checkbox_prefix(owner1_entry, False) == "[ ] "
    assert list_view._render_checkbox_prefix(owner1_entry, True) == "[x] "
    assert list_view._render_checkbox_prefix(owner1_entry, "partial") == "[-] "
    assert list_view._render_checkbox_prefix(child_entry, False) == "[ ] "
    assert list_view._render_checkbox_prefix(child_entry, True) == "[x] "

    # Toggling child marks child selected and parent tri-state partial
    list_view._toggle_selection(child_entry)
    selected = list_view.get_selected_items()
    assert selected == [child_entry]
    assert list_view._item_selection_state(child_entry) is True
    assert list_view._item_selection_state(owner1_entry) == "partial"
    assert list_view._render_checkbox_prefix(owner1_entry, list_view._item_selection_state(owner1_entry)) == "[-] "

    # Toggling parent selects parent and all descendants
    list_view.clear_selected_items()
    list_view._toggle_selection(owner1_entry)
    assert list_view._item_selection_state(owner1_entry) is True
    assert list_view._item_selection_state(child_entry) is True
    assert list_view._render_checkbox_prefix(owner1_entry, True) == "[x] "
    assert list_view._render_checkbox_prefix(child_entry, True) == "[x] "

    # Collapsing nested targets collapses parent and child to just parent
    collapsed = list_view._collapse_nested_targets([owner1_entry, child_entry])
    assert collapsed == [owner1_entry]

    # Granular child deletion triggers only for child if only child selected
    list_view.clear_selected_items()
    list_view._toggle_selection(child_entry)
    list_view._trigger_delete()
    assert list_view.state.confirm_delete is True
    assert list_view.state.pending_delete_items == [child_entry]
    summary = list_view._items_summary(list_view.state.pending_delete_items)
    assert "1 file" in summary
    assert "5 B" in summary

    # Expand all / collapse all
    tree.collapse_all()
    assert len(tree.expanded) == 0
    tree.toggle_expand_all()
    assert owner1_entry.path in tree.expanded
    tree.toggle_expand_all()
    assert len(tree.expanded) == 0

    # Delete all only selects depth == 0 entries, avoiding duplication
    list_view._trigger_delete_all()
    assert list_view.state.confirm_delete_all is True
    assert len(list_view.state.pending_delete_items) == 2
    assert all(e.depth == 0 for e in list_view.state.pending_delete_items)
    all_summary = list_view._items_summary(list_view.state.pending_delete_items)
    assert "2 files" in all_summary
    assert "7 B" in all_summary

    # Test delete execution and undo lifecycle
    trash_root = destination / "_partial" / ".trash"

    def delete_handler(targets):
        moved = []
        for target in targets:
            trash_dest = trash_root / f"{target.name}_t1"
            trash_root.mkdir(parents=True, exist_ok=True)
            target.path.rename(trash_dest)
            moved.append((target.path, trash_dest))
        return moved

    def undo_handler(targets, payload):
        for orig, dest in payload:
            dest.rename(orig)

    list_view.delete_handler = delete_handler
    list_view.undo_handler = undo_handler
    list_view._execute_delete([owner1_entry])
    assert not owner1.exists()
    assert len(list_view.state.undo_stack) == 1
    assert "Deleted 1 item(s)" in list_view.state.status_message

    list_view._undo()
    assert owner1.exists()
    assert len(list_view.state.undo_stack) == 0
    assert "Restored 1 item(s)" in list_view.state.status_message


def test_partial_expanding_selected_parent_propagates_selection_and_persists_on_collapse(tmp_path: Path) -> None:
    destination = tmp_path / "library"
    owner1 = destination / "_partial" / "owner1"
    owner2 = destination / "_partial" / "owner2"
    album1 = owner1 / "album1"
    album2 = owner1 / "album2"
    album1.mkdir(parents=True)
    album2.mkdir(parents=True)
    owner2.mkdir(parents=True)
    (album1 / "001.jpg").write_bytes(b"123")
    (album2 / "002.jpg").write_bytes(b"456")
    (owner2 / "003.jpg").write_bytes(b"789")

    _root, entries, sizes = build_partial_inventory(destination)
    tree = PartialTree(entries, sizes)
    owner1_entry = next(e for e in entries if e.name == "owner1")

    # Initial visible list has only root folders
    initial_visible = tree.visible("size", True)
    assert len(initial_visible) == 2

    list_view = PartialInteractiveList(
        items=initial_visible,
        sorters={"size": lambda e: e.size, "name": lambda e: e.name},
        formatter=lambda *args: "line",
        filter_func=lambda *args: True,
        initial_sort="size",
        initial_order="desc",
        multi_select=True,
        render_checkbox=True,
        enable_delete=True,
        files_extractor=lambda e: e.files,
        size_extractor=lambda e: e.size,
        item_key_func=lambda e: str(e.path),
    )

    # 1. Select owner1 while collapsed
    list_view._toggle_selection(owner1_entry)
    assert list_view._item_selection_state(owner1_entry) is True
    assert list_view._render_checkbox_prefix(owner1_entry, True) == "[x] "

    # 2. Expand owner1 -> loaded children must automatically be selected ([x]), parent remains [x]
    tree.toggle(owner1_entry)
    list_view.state.items = tree.visible("size", True)
    list_view._update_visible_items()

    expanded_items = list_view.state.items
    assert len(expanded_items) == 4
    album1_entry = next(e for e in expanded_items if e.name == "album1")
    album2_entry = next(e for e in expanded_items if e.name == "album2")

    assert list_view._item_selection_state(album1_entry) is True
    assert list_view._item_selection_state(album2_entry) is True
    assert list_view._item_selection_state(owner1_entry) is True
    assert list_view._render_checkbox_prefix(owner1_entry, True) == "[x] "
    assert list_view._render_checkbox_prefix(album1_entry, True) == "[x] "
    assert list_view._render_checkbox_prefix(album2_entry, True) == "[x] "

    # 3. Unselect album2 -> owner1 becomes partial ([-]), album1 remains [x]
    list_view._toggle_selection(album2_entry)
    assert list_view._item_selection_state(album2_entry) is False
    assert list_view._item_selection_state(album1_entry) is True
    assert list_view._item_selection_state(owner1_entry) == "partial"
    assert list_view._render_checkbox_prefix(owner1_entry, "partial") == "[-] "

    # 4. Collapse owner1 -> owner1 shows partial ([-]) because album1 is still selected inside it
    tree.toggle(owner1_entry)
    list_view.state.items = tree.visible("size", True)
    list_view._update_visible_items()

    assert len(list_view.state.items) == 2
    assert list_view._item_selection_state(owner1_entry) == "partial"
    assert list_view._render_checkbox_prefix(owner1_entry, "partial") == "[-] "

    # 5. Re-expand owner1 -> album1 remains selected, album2 remains unselected, owner1 remains partial
    tree.toggle(owner1_entry)
    list_view.state.items = tree.visible("size", True)
    list_view._update_visible_items()

    album1_entry = next(e for e in list_view.state.items if e.name == "album1")
    album2_entry = next(e for e in list_view.state.items if e.name == "album2")
    assert list_view._item_selection_state(album1_entry) is True
    assert list_view._item_selection_state(album2_entry) is False
    assert list_view._item_selection_state(owner1_entry) == "partial"



