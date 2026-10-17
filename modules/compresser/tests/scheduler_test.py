from pathlib import Path
import threading

import pytest

from compresser import CompressionEngine, CompressionStrategy, ImageMetadata, ImageResult
from compresser.scheduler import MemoryScheduler


def test_reservations_fill_unused_space_without_exceeding_budget():
    big1, big2, small = object(), object(), object()
    queue = MemoryScheduler([(big1, 90), (big2, 90), (small, 10)], 100, 3)
    assert queue.next_job() == (big1, 90)
    assert queue.next_job() == (small, 10)
    assert queue.next_job() is None
    queue.release(90)
    assert queue.next_job() == (big2, 90)
    assert queue.peak_reserved_bytes == 100


def test_large_head_cannot_be_bypassed_forever():
    head, small1, small2 = object(), object(), object()
    queue = MemoryScheduler([(head, 90), (small1, 10), (small2, 10)], 100, 1)
    queue.reserved_bytes = 80
    assert queue.next_job() == (small1, 10)
    queue.release(10)
    assert queue.next_job() is None  # Drain older reservations to admit head next.
    queue.release(80)
    assert queue.next_job() == (head, 90)


def test_mixed_jobs_run_together_and_rejected_images_do_not_cap_pool(monkeypatch):
    import compresser.engine as module

    monkeypatch.setattr(module.os, "cpu_count", lambda: 8)
    images = [
        ImageMetadata(Path("oversized.png"), "PNG", 6000, 6000, 1),
        ImageMetadata(Path("big.png"), "PNG", 3000, 3000, 1),
        ImageMetadata(Path("small.png"), "PNG", 40, 40, 1),
    ]
    barrier = threading.Barrier(2)
    engine = CompressionEngine()

    def work(img, *args, **kwargs):
        assert img.path.name != "oversized.png"
        barrier.wait(timeout=5)
        return ImageResult(img.path, img.path, 1, 1, "PNG", "PNG")

    monkeypatch.setattr(engine, "_compress_image_owned", work)
    events = []
    batch = engine.compress_batch(images, CompressionStrategy("test"), threads=8, activity_callback=events.append)
    assert batch.failed_count == 1
    assert max(event["active_workers"] for event in events) == 2
    assert batch.worker_diagnostics["peak_reserved_bytes"] <= module.MEMORY_BUDGET_BYTES
    assert all(event["reserved_bytes"] <= module.MEMORY_BUDGET_BYTES for event in events)


@pytest.mark.parametrize("budget", [0, 63 * 1024**2])
def test_aggregate_budget_is_bounded(budget):
    with pytest.raises(ValueError, match="Aggregate memory"):
        CompressionEngine(memory_budget_bytes=budget)


def test_aggregate_budget_allows_large_allocation():
    engine = CompressionEngine(memory_budget_bytes=16384 * 1024**2)
    assert engine.memory_budget_bytes == 16384 * 1024**2


def test_larger_aggregate_budget_does_not_remove_decode_limit():
    image = ImageMetadata(Path("huge.png"), "PNG", 6000, 6000, 100)
    batch = CompressionEngine(memory_budget_bytes=4096 * 1024**2).compress_batch([image], CompressionStrategy("test"))
    assert batch.failed_count == 1
    assert "per-image" in batch.results[0].error
    assert batch.worker_diagnostics["peak_reserved_bytes"] == 0


def test_invalid_cli_budget_rejected_before_scanning(tmp_path):
    from compresser.cli import main

    with pytest.raises(SystemExit) as result:
        main(["-i", str(tmp_path / "does-not-exist"), "-B", "63"])
    assert result.value.code == 2
