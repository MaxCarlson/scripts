import json
import sqlite3

import pytest
from PIL import Image

from compresser.inventory import InventoryStore
from compresser.scanner import scan_directory
from compresser.cli import main


def test_refresh_reuses_headers_and_removes_deleted_files(tmp_path, monkeypatch):
    import compresser.scanner as scanner

    root = tmp_path / "library"
    root.mkdir()
    path = root / "01.jpg"
    Image.new("RGB", (40, 40)).save(path)
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    first, images = scan_directory(root, inventory=store)
    original = scanner.inspect_image_file
    monkeypatch.setattr(
        scanner,
        "inspect_image_file",
        lambda *a, **k: pytest.fail("Reopened unchanged header"),
    )
    assert scan_directory(root, inventory=InventoryStore(store.path)) == (first, images)
    monkeypatch.setattr(scanner, "inspect_image_file", original)
    path.unlink()
    Image.new("RGB", (50, 50)).save(root / "02.png")
    summary, images = scan_directory(root, inventory=store)
    assert summary.total_images == 1 and images[0].path.name == "02.png"
    with sqlite3.connect(store.path) as connection:
        rows = connection.execute("SELECT path FROM inventory_headers").fetchall()
        assert rows == [(str(root / "02.png"),)]


def test_abort_does_not_publish_snapshot(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    Image.new("RGB", (40, 40)).save(root / "01.png")
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    scan_directory(root, inventory=store)
    with sqlite3.connect(store.path) as connection:
        before = connection.execute("SELECT report FROM inventory_scans").fetchall()
    with pytest.raises(KeyboardInterrupt):
        scan_directory(
            root,
            inventory=store,
            progress_callback=lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()),
        )
    with sqlite3.connect(store.path) as connection:
        assert (
            connection.execute("SELECT report FROM inventory_scans").fetchall()
            == before
        )


def test_inventory_only_reports_extensions_separately(tmp_path, capsys):
    root = tmp_path / "library"
    gallery = root / "manga"
    gallery.mkdir(parents=True)
    Image.new("RGB", (40, 40)).save(gallery / "01.jpg", format="PNG")
    (gallery / "broken.jpg").write_bytes(b"not an image")
    path = tmp_path / "state" / ".compresser" / "library" / "inventory.sqlite3"
    assert main(["-i", str(root), "-l", "-I", str(tmp_path / "state")]) == 0
    report = json.loads(capsys.readouterr().out)
    row = report["galleries"]["manga"]
    assert row["extensions"][".jpg"]["images"] == 1
    assert row["formats"]["PNG"]["images"] == 1
    with sqlite3.connect(path) as connection:
        scan = json.loads(
            connection.execute("SELECT report FROM inventory_scans").fetchone()[0]
        )
    assert scan["unreadable_images"] == 1
    assert main(["-i", str(root), "-l", "-I", str(root / "bad.sqlite3")]) == 2
    with pytest.raises(SystemExit):
        main(["-i", str(root), "-l", "-b"])


def test_inventory_progress_tracks_folders_files_bytes_and_rates(tmp_path):
    import io
    from compresser.inventory_ui import InventoryProgress

    root = tmp_path / "library"
    gal_a = root / "gal_a"
    gal_b = root / "gal_b"
    gal_a.mkdir(parents=True)
    gal_b.mkdir(parents=True)
    Image.new("RGB", (40, 40)).save(gal_a / "01.png")
    Image.new("RGB", (40, 40)).save(gal_b / "02.png")
    (gal_b / "corrupt.jpg").write_bytes(b"bad")

    buf = io.StringIO()
    prog = InventoryProgress(
        root, depth="headers", enabled=True, stream=buf, interactive=False
    )
    store = InventoryStore(tmp_path / "inv.sqlite3")
    scan_directory(root, inventory=store, progress=prog)
    prog._maybe_render(force=True)
    prog.close()

    assert prog.folders_processed == 2
    assert prog.files_processed == 3
    assert prog.headers_inspected == 3
    assert prog.headers_reused == 0
    assert prog.excluded_or_unreadable == 1
    assert prog.bytes_processed > 0
    output = buf.getvalue()
    assert "Folders: 2" in output
    assert "Files: 3/3" in output
    assert "files/s" in output
