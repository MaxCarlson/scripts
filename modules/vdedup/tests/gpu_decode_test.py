from __future__ import annotations

from pathlib import Path

from vdedup import gpu_decode
from vdedup.gpu_decode import DecodeResult, decode_frames_at_timestamps


def test_decode_empty_timestamps_returns_structured_error():
    result = decode_frames_at_timestamps(Path("missing.mp4"), [], use_gpu=True)

    assert isinstance(result, DecodeResult)
    assert result.succeeded is False
    assert result.frames == []
    assert result.error == "no timestamps requested"
    assert result.attempted_gpu is True


def test_decode_auto_falls_back_to_cpu_with_structured_gpu_error(monkeypatch):
    def fail_gpu(path, timestamps, device_id):
        raise RuntimeError("gpu unavailable")

    def cpu_frames(path, timestamps):
        return ["cpu-frame"]

    monkeypatch.setattr(gpu_decode, "_decode_gpu", fail_gpu)
    monkeypatch.setattr(gpu_decode, "_decode_cpu", cpu_frames)

    result = decode_frames_at_timestamps(Path("video.mp4"), [1.0], use_gpu=True)

    assert result.succeeded is True
    assert result.backend == "cpu_ffmpeg"
    assert result.fallback_used is True
    assert result.gpu_error == "gpu unavailable"
    assert result.frames == ["cpu-frame"]


def test_decode_off_uses_cpu_without_gpu_attempt(monkeypatch):
    def fail_if_called(path, timestamps, device_id):
        raise AssertionError("GPU should not be attempted")

    monkeypatch.setattr(gpu_decode, "_decode_gpu", fail_if_called)
    monkeypatch.setattr(gpu_decode, "_decode_cpu", lambda path, timestamps: ["cpu-frame"])

    result = decode_frames_at_timestamps(Path("video.mp4"), [1.0], use_gpu=False)

    assert result.succeeded is True
    assert result.backend == "cpu_ffmpeg"
    assert result.attempted_gpu is False
    assert result.fallback_used is False


def test_decode_failure_distinguishes_zero_frames(monkeypatch):
    monkeypatch.setattr(gpu_decode, "_decode_gpu", lambda path, timestamps, device_id: [])
    monkeypatch.setattr(gpu_decode, "_decode_cpu", lambda path, timestamps: [])

    result = decode_frames_at_timestamps(Path("corrupt.mp4"), [1.0], use_gpu=True)

    assert result.succeeded is False
    assert result.backend is None
    assert result.gpu_error == "GPU decoder returned zero frames"
    assert result.cpu_error == "CPU decoder returned zero frames"
