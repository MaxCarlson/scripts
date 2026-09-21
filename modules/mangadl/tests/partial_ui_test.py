from pathlib import Path

from mangadl.models import InputUrl
from mangadl.partial_reconcile import partial_key
from mangadl.partial_ui import PartialTree, build_partial_inventory, partial_details
from mangadl.state import StateStore


def test_inventory_recovers_legacy_url_and_recursive_size(tmp_path: Path) -> None:
    destination, url = tmp_path / "library", "https://example.test/gallery/one"
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
    root, entries, sizes = build_partial_inventory(destination)
    assert root == destination / "_partial" and entries[0].url == url
    assert (entries[0].files, entries[0].size) == (1, 5) and sizes[owner] == (1, 5)
    assert f"URL: {url}" in partial_details(entries[0])


def test_partial_tree_expands_and_sorts_hierarchically(tmp_path: Path) -> None:
    destination = tmp_path / "library"
    first, second = destination / "_partial" / "first", destination / "_partial" / "second"
    (first / "z-child").mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "z-child" / "001.jpg").write_bytes(b"12345")
    (second / "001.jpg").write_bytes(b"1")
    _root, entries, sizes = build_partial_inventory(destination)
    tree = PartialTree(entries, sizes)
    first_entry = next(entry for entry in entries if entry.name == "first")
    tree.toggle(first_entry)
    assert [entry.name for entry in tree.visible("size", True)[:2]] == ["first", "z-child"]
    tree.toggle(first_entry)
    assert [entry.name for entry in tree.visible("name", False)] == ["first", "second"]
