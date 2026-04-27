from __future__ import annotations

from pathlib import Path

from PIL import Image

from vdedup import gpu_decode, gpu_fingerprint
from vdedup.gpu_decode import DecodeResult
from vdedup.gpu_fingerprint import extract_video_signature
from vdedup.models import FrameSignature, VideoSignature


def test_frame_signature_json_round_trip():
    frame = FrameSignature(
        path=Path("a.mp4"),
        video_id="a.mp4",
        frame_index=1,
        timestamp_seconds=2.5,
        phash64=123,
        entropy=3.5,
        mean_luma=0.4,
        valid_for_matching=True,
    )

    assert FrameSignature.from_json_dict(frame.to_json_dict()) == frame


def test_video_signature_json_round_trip():
    frame = FrameSignature(Path("a.mp4"), "a.mp4", 0, 1.0, 99, 2.0, 0.5, True)
    signature = VideoSignature(Path("a.mp4"), "a.mp4", 10.0, 1, 1, [frame], "cpu_ffmpeg", "balanced")

    assert VideoSignature.from_json_dict(signature.to_json_dict()) == signature


def test_extract_video_signature_uses_supplied_duration_and_decode_result(monkeypatch):
    frames = [Image.new("RGB", (16, 16), (20, 100, 200))]

    def fake_decode(path, timestamps, device_id=0, use_gpu=True):
        return DecodeResult(
            path=path,
            requested_timestamps=timestamps,
            frames=frames,
            backend="cpu_ffmpeg",
            attempted_gpu=use_gpu,
            fallback_used=False,
        )

    monkeypatch.setattr(gpu_decode, "decode_frames_at_timestamps", fake_decode)
    monkeypatch.setattr(gpu_fingerprint, "compute_phash64_batch", lambda frames, use_gpu=True: [123])
    monkeypatch.setattr(gpu_fingerprint, "compute_frame_quality", lambda frames, use_gpu=True: [(3.0, 0.5)])
    monkeypatch.setattr(gpu_fingerprint, "_compute_frame_std_luma", lambda frame: 0.5)

    signature = extract_video_signature(Path("a.mp4"), duration_seconds=10.0, use_gpu=False)

    assert signature is not None
    assert signature.duration_seconds == 10.0
    assert signature.extraction_backend == "cpu_ffmpeg"
    assert signature.sampled_frame_count == 1
    assert signature.valid_frame_count == 1
    assert signature.signatures[0].phash64 == 123


def test_extract_video_signature_returns_none_for_structured_decode_failure(monkeypatch):
    def fake_decode(path, timestamps, device_id=0, use_gpu=True):
        return DecodeResult(
            path=path,
            requested_timestamps=timestamps,
            frames=[],
            backend=None,
            attempted_gpu=use_gpu,
            fallback_used=True,
            error="decode failed",
        )

    monkeypatch.setattr(gpu_decode, "decode_frames_at_timestamps", fake_decode)

    assert extract_video_signature(Path("bad.mp4"), duration_seconds=10.0) is None
