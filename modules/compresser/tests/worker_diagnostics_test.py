from pathlib import Path
import threading

from compresser import CompressionEngine, CompressionStrategy, ImageMetadata, ImageResult


def test_oversized_image_is_preflight_rejected_without_worker(monkeypatch):
    import compresser.engine as module

    monkeypatch.setattr(module.os, "cpu_count", lambda: 16)
    images = [ImageMetadata(Path("huge.png"), "PNG", 6000, 6000, 100)]
    engine = CompressionEngine()
    monkeypatch.setattr(
        engine,
        "_compress_image_owned",
        lambda img, *args, **kw: ImageResult(img.path, img.path, 100, 100, "PNG", "PNG"),
    )
    events = []
    batch = engine.compress_batch(images, CompressionStrategy("test"), threads=10, activity_callback=events.append)
    info = batch.worker_diagnostics
    assert info["requested_workers"] == 10 and info["effective_workers"] == 0
    assert info["limiter"] == "no eligible jobs" and not info["includes_oversized_images"]
    assert info["preflight_rejected_images"] == 1 and batch.failed_count == 1
    assert events[0]["active_workers"] == 0
    assert not any(event["active_workers"] for event in events)
    assert events[-1]["completed_workers"] == 1 and events[-1]["active_workers"] == 0


def test_active_counters_are_real_concurrency(monkeypatch):
    import compresser.engine as module

    monkeypatch.setattr(module.os, "cpu_count", lambda: 8)
    images = [ImageMetadata(Path(f"{number}.png"), "PNG", 40, 40, 100) for number in range(2)]
    barrier = threading.Barrier(2)
    engine = CompressionEngine()

    def work(img, *args, **kwargs):
        barrier.wait(timeout=5)
        return ImageResult(img.path, img.path, 100, 100, "PNG", "PNG")

    monkeypatch.setattr(engine, "_compress_image_owned", work)
    events = []
    engine.compress_batch(images, CompressionStrategy("test"), threads=2, activity_callback=events.append)
    assert max(event["active_workers"] for event in events) == 2
    assert events[-1]["completed_workers"] == 2 and events[-1]["remaining_images"] == 0
