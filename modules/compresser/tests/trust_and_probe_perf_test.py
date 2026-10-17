"""Reduce trust-path work without retaining ancestor trust between operations."""

from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from compresser.inventory import InventoryStore
from compresser.scanner import scan_directory
from compresser.snapshots import SelectionSnapshot


def _trusted(tmp_path):
    root = tmp_path / "library"
    chapter = root / "gallery" / "chapter"
    chapter.mkdir(parents=True)
    for number in range(8):
        Image.new("RGB", (40, 40)).save(chapter / f"{number}.png")
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    _, images = scan_directory(root, inventory=store)
    snapshot = SelectionSnapshot(store, root, owner="test")
    snapshot.publish(images)
    images, _ = snapshot.load()
    return snapshot, images, chapter


def test_shared_ancestors_checked_twice_per_batch_not_per_image(tmp_path, monkeypatch):
    snapshot, images, chapter = _trusted(tmp_path)
    original = Path.lstat
    counts = Counter()

    def observed(path, *a, **k):
        counts[path] += 1
        return original(path, *a, **k)

    monkeypatch.setattr(Path, "lstat", observed)
    snapshot.validate_selected(images)
    assert counts[chapter] == 2
    assert all(counts[image.path] == 1 for image in images)
    snapshot.validate_selected(images)
    assert counts[chapter] == 4  # No trust retained across comparison stages.


def test_ancestor_replaced_during_validation_is_rejected(tmp_path, monkeypatch):
    snapshot, images, chapter = _trusted(tmp_path)
    original = Path.lstat
    calls = 0

    def replaced(path, *a, **k):
        nonlocal calls
        info = original(path, *a, **k)
        if path == chapter:
            calls += 1
            if calls > 1:
                return SimpleNamespace(
                    st_mode=info.st_mode, st_dev=info.st_dev, st_ino=info.st_ino + 1, st_file_attributes=0
                )
        return info

    monkeypatch.setattr(Path, "lstat", replaced)
    with pytest.raises(ValueError, match="refresh"):
        snapshot.validate_selected(images)


def test_changed_selected_file_still_rejected_after_previous_validation(tmp_path):
    snapshot, images, _ = _trusted(tmp_path)
    snapshot.validate_selected(images)
    Image.new("RGB", (50, 50)).save(images[0].path)
    with pytest.raises(ValueError, match="refresh"):
        snapshot.validate_selected(images)
