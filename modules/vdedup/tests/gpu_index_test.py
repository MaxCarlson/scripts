from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from vdedup.gpu_index import HashBandIndex
from vdedup.models import FrameSignature, VideoSignature


@dataclass(slots=True)
class FakeFrame:
    frame_index: int
    timestamp_seconds: float
    phash64: int | None = None
    dhash64: int | None = None
    valid_for_matching: bool = True


def _signature(path: str, frames: list[object]) -> VideoSignature:
    return VideoSignature(
        path=Path(path),
        video_id=path,
        duration_seconds=10.0,
        sampled_frame_count=len(frames),
        valid_frame_count=sum(1 for frame in frames if getattr(frame, "valid_for_matching", False)),
        signatures=frames,  # type: ignore[arg-type]
        extraction_backend="cpu_ffmpeg",
        sampling_profile="balanced",
    )


def test_hash_band_index_empty():
    index = HashBandIndex()

    assert index.candidate_video_pairs() == {}
    assert index.frame_refs_for_video("missing") == []


def test_hash_band_index_adds_valid_frames_only():
    frame = FrameSignature(Path("a.mp4"), "a.mp4", 0, 1.0, 0x1234, 3.0, 0.5, True)
    index = HashBandIndex()

    index.add_video(_signature("a.mp4", [frame]))

    assert len(index.frame_refs_for_video("a.mp4")) == 1


def test_hash_band_index_ignores_invalid_frames():
    frame = FrameSignature(Path("a.mp4"), "a.mp4", 0, 1.0, 0x1234, 3.0, 0.5, False)
    index = HashBandIndex()

    index.add_video(_signature("a.mp4", [frame]))

    assert index.frame_refs_for_video("a.mp4") == []


def test_hash_band_index_uses_selected_hash_field():
    left = _signature("a.mp4", [FakeFrame(0, 1.0, phash64=0x1111, dhash64=0x9999)])
    right = _signature("b.mp4", [FakeFrame(0, 1.0, phash64=0x2222, dhash64=0x9999)])
    index = HashBandIndex()

    index.add_video(left, hash_field="dhash64")
    index.add_video(right, hash_field="dhash64")

    assert ("a.mp4", "b.mp4") in index.candidate_video_pairs()


def test_hash_band_index_skips_missing_hash():
    index = HashBandIndex()

    index.add_video(_signature("a.mp4", [FakeFrame(0, 1.0, phash64=None)]))

    assert index.frame_refs_for_video("a.mp4") == []


def test_hash_band_index_generates_pair_for_shared_band():
    left = _signature("a.mp4", [FakeFrame(0, 1.0, phash64=0xAAAA_0000_0000_1234)])
    right = _signature("b.mp4", [FakeFrame(0, 1.0, phash64=0xBBBB_1111_2222_1234)])
    index = HashBandIndex()

    index.add_video(left)
    index.add_video(right)

    assert index.candidate_video_pairs()[("a.mp4", "b.mp4")] == 1


def test_hash_band_index_does_not_generate_self_pair():
    signature = _signature(
        "a.mp4",
        [
            FakeFrame(0, 1.0, phash64=0x1234),
            FakeFrame(1, 2.0, phash64=0x1234),
        ],
    )
    index = HashBandIndex()

    index.add_video(signature)

    assert index.candidate_video_pairs() == {}


def test_hash_band_index_pair_order_is_stable():
    index = HashBandIndex()

    index.add_video(_signature("z.mp4", [FakeFrame(0, 1.0, phash64=0x1234)]))
    index.add_video(_signature("a.mp4", [FakeFrame(0, 1.0, phash64=0x1234)]))

    assert list(index.candidate_video_pairs()) == [("a.mp4", "z.mp4")]


def test_hash_band_index_frame_refs_for_video():
    index = HashBandIndex()
    index.add_video(_signature("a.mp4", [FakeFrame(3, 4.0, phash64=0x1234)]))

    refs = index.frame_refs_for_video("a.mp4")

    assert len(refs) == 1
    assert refs[0].frame_index == 3
    assert refs[0].timestamp_seconds == 4.0


def test_hash_band_index_raises_for_invalid_band_config():
    with pytest.raises(ValueError):
        HashBandIndex(bands=3, bits_per_band=16)
