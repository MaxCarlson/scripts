"""Reduce trust-path work without retaining ancestor trust between operations."""

from collections import Counter
from pathlib import Path
from types import SimpleNamespace
import threading
import sqlite3
from dataclasses import replace

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


def test_first_encode_starts_before_later_cache_probes(tmp_path, monkeypatch):
    from compresser.engine import CompressionEngine
    from compresser.models import CompressionStrategy

    _, images, _ = _trusted(tmp_path)
    engine = CompressionEngine()
    started = threading.Event()
    original_encode = engine._measure_image
    original_probe = engine._probe_cached
    probes = []

    def encode(*args, **kwargs):
        started.set()
        return original_encode(*args, **kwargs)

    def probe(image, strategy):
        if probes:
            assert started.wait(2), "All cache probes blocked first encoder dispatch"
        probes.append(image.path)
        return original_probe(image, strategy)

    monkeypatch.setattr(engine, "_measure_image", encode)
    monkeypatch.setattr(engine, "_probe_cached", probe)
    try:
        result = engine.compress_batch(images, CompressionStrategy("png", format="png", method=0), threads=2)
        assert result.failed_count == 0
        assert len(probes) == len(set(probes)) == len(images)
    finally:
        engine.cache.close()


@pytest.mark.parametrize("persistent", [True, False])
def test_bulk_cache_matches_scalar_and_rejects_stale_observations(tmp_path, persistent):
    from compresser.cache import AnalysisCache
    from compresser.inventory_pipeline import FileObservation
    from compresser.models import CompressionStrategy, ImageResult

    _, images, _ = _trusted(tmp_path)
    strategy = CompressionStrategy("webp", format="webp", method=0)
    path = tmp_path / "trials.sqlite3" if persistent else None
    with AnalysisCache(path=path) as cache:
        for image in images[:4]:
            cache.set(
                image.path,
                strategy,
                ImageResult(image.path, image.path, image.size_bytes, image.size_bytes, image.format, image.format),
            )
        requests = [
            (image, strategy, FileObservation(image.path, image.path.parent, image.path.lstat())) for image in images
        ]
        expected = [cache.get(image.path, strategy) for image in images]
        before = cache.diagnostics()
        assert cache.get_many(requests) == expected
        after = cache.diagnostics()
        assert after["lookup_hits"] - before["lookup_hits"] == 4
        images[0].path.write_bytes(b"changed")
        with pytest.raises(RuntimeError, match="changed"):
            cache.get_many(requests)


@pytest.mark.parametrize("case", ["legacy", "malformed", "invalid", "evicted", "refresh", "settings", "runtime"])
def test_bulk_cache_preserves_legacy_invalidation_and_diagnostics(tmp_path, case):
    from compresser.cache import AnalysisCache
    from compresser.inventory_pipeline import FileObservation
    from compresser.models import CompressionStrategy, ImageResult

    _, images, _ = _trusted(tmp_path)
    image = images[0]
    strategy = CompressionStrategy("webp", format="webp", method=0)
    database = tmp_path / "trials.sqlite3"
    with AnalysisCache(path=database) as cache:
        cache.set(
            image.path,
            strategy,
            ImageResult(image.path, image.path, image.size_bytes, image.size_bytes, image.format, image.format),
        )
        primary, legacy = cache._make_key(image.path, strategy), cache._make_key(image.path, strategy, legacy=True)
    with sqlite3.connect(database) as db:
        if case == "legacy":
            db.execute("UPDATE entries SET key=? WHERE key=?", (legacy, primary))
        elif case in ("malformed", "invalid"):
            db.execute(
                "UPDATE entries SET data=? WHERE key=?", ("bad-json" if case == "malformed" else '{"bad":1}', primary)
            )
        elif case == "evicted":
            db.execute("DELETE FROM entries")
    if case == "settings":
        strategy = replace(strategy, method=1)
    with AnalysisCache(path=database, reuse_persistent=case != "refresh") as scalar, AnalysisCache(
        path=database, reuse_persistent=case != "refresh"
    ) as bulk:
        if case == "runtime":
            scalar.identity = bulk.identity = "changed-runtime"
        expected = scalar.get(image.path, strategy)
        request = (image, strategy, FileObservation(image.path, image.path.parent, image.path.lstat()))
        assert bulk.get_many([request]) == [expected]
        for key in ("lookup_hits", "lookup_misses", "miss_reasons", "invalidation_causes"):
            assert bulk.diagnostics()[key] == scalar.diagnostics()[key]
