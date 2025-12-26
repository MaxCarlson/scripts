from __future__ import annotations

import types

from vdedup.video_dedupe import (
    _apply_quality_defaults,
    _default_thread_count,
    _normalize_patterns,
    _quality_default_config,
)


def test_normalize_patterns_deduplicates_and_normalizes() -> None:
    patterns = _normalize_patterns(["*.mp4", "mp4", " MP4 ", "*.MKV", "*.mkv", "", None])  # type: ignore[arg-type]
    assert patterns == ["*.mp4", "*.mkv"]


def test_default_threads_reserve_four_cores(monkeypatch):
    monkeypatch.setattr("vdedup.video_dedupe.os.cpu_count", lambda: 16)
    assert _default_thread_count() == 12


def test_quality_defaults_escalate_for_high_modes():
    base = _quality_default_config("2")
    thorough = _quality_default_config("6")
    assert base["phash_frames"] < thorough["phash_frames"]
    assert base["duration_tolerance"] < thorough["duration_tolerance"]
    assert thorough["include_partials"] is True


def test_quality_defaults_respect_user_overrides():
    namespace = types.SimpleNamespace(
        quality="6",
        duration_tolerance=8.0,
        phash_frames=None,
        phash_threshold=None,
        subset_min_ratio=None,
        include_partials=None,
        threads=None,
    )
    _apply_quality_defaults(namespace)  # type: ignore[arg-type]
    assert namespace.duration_tolerance == 8.0  # unchanged
    assert namespace.phash_frames is not None
    assert namespace.threads is not None
