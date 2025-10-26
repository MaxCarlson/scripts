from __future__ import annotations

from vdedup.video_dedupe import _normalize_patterns


def test_normalize_patterns_deduplicates_and_normalizes() -> None:
    patterns = _normalize_patterns(["*.mp4", "mp4", " MP4 ", "*.MKV", "*.mkv", "", None])  # type: ignore[arg-type]
    assert patterns == ["*.mp4", "*.mkv"]
