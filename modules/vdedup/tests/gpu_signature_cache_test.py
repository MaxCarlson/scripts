from __future__ import annotations

from pathlib import Path

from vdedup.gpu_signature_cache import GpuSignatureCache
from vdedup.models import FrameSignature, VideoSignature


def _signature(path: Path) -> VideoSignature:
    frame = FrameSignature(path, str(path), 0, 1.0, 42, 2.5, 0.4, True)
    return VideoSignature(path, str(path), 10.0, 1, 1, [frame], "cpu_ffmpeg", "balanced")


def test_cache_put_get_round_trip(tmp_path):
    cache_path = tmp_path / "gpu-cache.jsonl"
    path = tmp_path / "video.mp4"
    signature = _signature(path)
    cache = GpuSignatureCache(cache_path)

    cache.put(signature, size=100, mtime_ns=200)
    loaded = GpuSignatureCache(cache_path).get(path, 100, 200, "balanced", "cpu_ffmpeg")

    assert loaded == signature


def test_cache_key_changes_when_mtime_changes(tmp_path):
    cache_path = tmp_path / "gpu-cache.jsonl"
    path = tmp_path / "video.mp4"
    cache = GpuSignatureCache(cache_path)

    cache.put(_signature(path), size=100, mtime_ns=200)

    assert GpuSignatureCache(cache_path).get(path, 100, 201, "balanced", "cpu_ffmpeg") is None


def test_cache_tolerates_corrupt_lines(tmp_path):
    cache_path = tmp_path / "gpu-cache.jsonl"
    path = tmp_path / "video.mp4"
    cache_path.write_text("{not json}\n", encoding="utf-8")
    cache = GpuSignatureCache(cache_path)

    assert cache.get(path, 100, 200, "balanced", "cpu_ffmpeg") is None
