"""Bounded inventory work, connection ownership, and interrupted publication."""

import json
import sqlite3
import threading

import pytest
from PIL import Image

from compresser.inventory import InventoryStore
from compresser.scanner import scan_directory
from compresser.snapshots import SelectionSnapshot
from compresser.timing import pipeline_scope


def test_one_run_reuses_connection_without_holding_scan_write_lock(tmp_path):
    root = tmp_path / "library"
    for name in ("a", "b"):
        folder = root / name
        folder.mkdir(parents=True)
        Image.new("RGB", (40, 40)).save(folder / "01.png")
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    with pipeline_scope() as metrics, store.run():
        all_images = []
        for folder in sorted(root.iterdir()):

            def independent_writer(*_):
                with sqlite3.connect(store.path, timeout=0.05) as db:
                    db.execute("CREATE TABLE IF NOT EXISTS writer_probe (id INTEGER)")
                    db.execute("INSERT INTO writer_probe VALUES(1)")

            _, images = scan_directory(folder, inventory=store, progress_callback=independent_writer)
            all_images.extend(images)
        SelectionSnapshot(store, root, owner="test").publish(all_images)
        assert metrics.report()["counters"]["inventory_connections"] == 1
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM writer_probe").fetchone()[0] == 2


def test_interrupted_refresh_keeps_previous_complete_selection(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    Image.new("RGB", (40, 40)).save(root / "01.png")
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    with store.run():
        _, images = scan_directory(root, inventory=store)
        SelectionSnapshot(store, root, owner="test").publish(images)
    with sqlite3.connect(store.path) as db:
        before = db.execute("SELECT report FROM inventory_selections").fetchone()[0]
    Image.new("RGB", (50, 50)).save(root / "02.png")
    with pytest.raises(KeyboardInterrupt), store.run():
        scan_directory(root, inventory=store, progress_callback=lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT report FROM inventory_selections").fetchone()[0] == before
        assert json.loads(before)["status"] == "complete"


def test_parallel_headers_collect_ready_results_and_keep_queue_bounded(tmp_path, monkeypatch):
    import compresser.scanner as scanner

    root = tmp_path / "library"
    root.mkdir()
    for i in range(132):
        Image.new("RGB", (40, 40), (i, 0, 0)).save(root / f"{i:02}.png")
    (root / "broken.png").write_bytes(b"not an image")
    original = scanner.inspect_image_file
    ready = threading.Event()
    barrier = threading.Barrier(2)
    owners = set()
    completed = []

    def inspect(path, **kwargs):
        owners.add(threading.get_ident())
        if path.name in ("00.png", "01.png"):
            barrier.wait(timeout=3)
        if path.name == "00.png":
            assert ready.wait(timeout=3), "Ready completions blocked behind the first future"
        return original(path, **kwargs)

    def progress(_, path):
        completed.append(path.name)
        if path.name == "01.png":
            ready.set()

    monkeypatch.setattr(scanner, "inspect_image_file", inspect)
    with pipeline_scope() as metrics:
        parallel = scan_directory(root, threads=2, progress_callback=progress)
    assert len(owners) == 2
    assert completed.index("01.png") < completed.index("00.png")
    assert metrics.report()["counters"]["inventory_pending_peak"] <= 4
    assert metrics.report()["counters"]["unreadable_images"] == 1
    monkeypatch.setattr(scanner, "inspect_image_file", original)
    assert parallel == scan_directory(root, threads=1)


@pytest.mark.parametrize("change", ["grow", "replace", "delete"])
def test_changed_source_during_header_inspection_fails_closed(tmp_path, monkeypatch, change):
    import compresser.scanner as scanner

    path = tmp_path / "01.png"
    Image.new("RGB", (40, 40)).save(path)
    original = scanner.inspect_image_file

    def inspect(candidate, **kwargs):
        result = original(candidate, **kwargs)
        if change == "delete":
            candidate.unlink()
        elif change == "replace":
            candidate.unlink()
            Image.new("RGB", (40, 40), "red").save(candidate)
        else:
            with candidate.open("ab") as stream:
                stream.write(b"changed")
        return result

    monkeypatch.setattr(scanner, "inspect_image_file", inspect)
    with pytest.raises((RuntimeError, FileNotFoundError), match="changed|cannot find|No such"):
        scan_directory(path, threads=2)


def test_refresh_prunes_only_visited_directories_and_batches_queries(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    for i in range(260):
        Image.new("RGB", (8, 8)).save(root / f"{i:03}.png")
    hidden = root / ".hidden"
    hidden.mkdir()
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    with store.run():
        scan_directory(root, inventory=store, threads=2)
    excluded_path = str(hidden / "old.png")
    with sqlite3.connect(store.path) as db:
        db.execute("INSERT INTO inventory_headers VALUES(?,?,?,?)", (excluded_path, 0, "old", "{}"))
    (root / "001.png").unlink()
    with pipeline_scope() as metrics, store.run():
        scan_directory(root, inventory=store, threads=2)
        # Two scoped lookups, schema statements, prune query and snapshot insert;
        # not one SQL SELECT per image.
        assert metrics.report()["counters"]["inventory_queries"] < 20
        assert metrics.report()["counters"].get("headers_inspected", 0) == 0
    with sqlite3.connect(store.path) as db:
        paths = {row[0] for row in db.execute("SELECT path FROM inventory_headers")}
    assert excluded_path in paths
    assert str(root / "001.png") not in paths


@pytest.mark.parametrize("failure", ["database is locked", "database or disk is full"])
def test_failed_cache_batch_preserves_completed_selection(tmp_path, monkeypatch, failure):
    import compresser.inventory as module

    root = tmp_path / "library"
    root.mkdir()
    Image.new("RGB", (40, 40)).save(root / "01.png")
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    with store.run():
        _, images = scan_directory(root, inventory=store)
        SelectionSnapshot(store, root, owner="test").publish(images)
    with sqlite3.connect(store.path) as db:
        before = db.execute("SELECT report FROM inventory_selections").fetchone()[0]
    Image.new("RGB", (50, 50)).save(root / "02.png")

    class FailingConnection(sqlite3.Connection):
        def executemany(self, sql, parameters):
            raise sqlite3.OperationalError(failure)

    monkeypatch.setattr(
        module, "connect_inventory", lambda *a, **k: sqlite3.connect(*a, **k, factory=FailingConnection)
    )
    with pytest.raises(sqlite3.OperationalError, match=failure), store.run():
        scan_directory(root, inventory=store)
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT report FROM inventory_selections").fetchone()[0] == before


def test_inventory_fingerprint_includes_observed_source_identity(tmp_path):
    path = tmp_path / "01.png"
    Image.new("RGB", (40, 40)).save(path)
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    scan_directory(path, inventory=store)
    with sqlite3.connect(store.path) as db:
        value = json.loads(db.execute("SELECT fingerprint FROM inventory_headers").fetchone()[0])
    info = path.lstat()
    assert value == [2, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_dev, info.st_ino]
