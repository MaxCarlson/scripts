from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

import pytest

from vdedup.pipeline import PipelineConfig, run_pipeline
from vdedup.progress import ProgressReporter


def _touch(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


@pytest.fixture()
def reporter() -> ProgressReporter:
    return ProgressReporter(enable_dash=False)


def test_scene_stage_groups_duplicates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reporter: ProgressReporter) -> None:
    root = tmp_path / "scene"
    a = root / "a.mp4"
    b = root / "b.mp4"
    c = root / "c.mp4"
    _touch(a, b"A" * 128)
    _touch(b, b"B" * 128)
    _touch(c, b"C" * 128)

    fingerprints: Dict[Path, Tuple[int, ...]] = {
        a.resolve(): (1, 2, 3, 4),
        b.resolve(): (1, 2, 3, 4),
        c.resolve(): (9, 9, 9, 9),
    }

    def fake_scene(path: Path, **_: object) -> Tuple[int, ...]:
        return fingerprints.get(path.resolve(), (9, 9, 9, 9))

    monkeypatch.setattr("vdedup.phash.compute_scene_fingerprint", fake_scene)

    cfg = PipelineConfig(threads=2, subset_detect=True)
    groups = run_pipeline(
        root=root,
        patterns=["*.mp4"],
        max_depth=None,
        selected_stages=[5],
        cfg=cfg,
        cache=None,
        reporter=reporter,
    )

    assert any(key.startswith("scene") for key in groups.keys())


def test_audio_stage_groups_duplicates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reporter: ProgressReporter) -> None:
    root = tmp_path / "audio"
    a = root / "clip_a.mp4"
    b = root / "clip_b.mp4"
    _touch(a, b"A" * 256)
    _touch(b, b"B" * 256)

    def fake_audio(path: Path, **_: object) -> Tuple[int, ...]:
        if path.name == "clip_a.mp4":
            return (10, 20, 30, 40, 50)
        if path.name == "clip_b.mp4":
            return (10, 20, 30, 40, 50)
        return (99, 98, 97, 96, 95)

    monkeypatch.setattr("vdedup.audio.compute_audio_fingerprint", fake_audio)

    cfg = PipelineConfig(threads=2, subset_detect=False)
    groups = run_pipeline(
        root=root,
        patterns=["*.mp4"],
        max_depth=None,
        selected_stages=[6],
        cfg=cfg,
        cache=None,
        reporter=reporter,
    )

    assert any(key.startswith("audio") for key in groups.keys())


def test_timeline_stage_detects_subset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reporter: ProgressReporter) -> None:
    root = tmp_path / "timeline"
    long_clip = root / "long.mp4"
    short_clip = root / "short.mp4"
    _touch(long_clip, b"L" * 512)
    _touch(short_clip, b"S" * 128)

    long_sig = tuple(range(1, 25))
    short_sig = tuple(range(5, 17))

    def fake_timeline(path: Path, **_: object) -> Tuple[int, ...]:
        if path.name == "long.mp4":
            return long_sig
        if path.name == "short.mp4":
            return short_sig
        return tuple()

    monkeypatch.setattr("vdedup.phash.compute_timeline_signature", fake_timeline)

    cfg = PipelineConfig(threads=2, subset_detect=True, subset_min_ratio=0.3)
    groups = run_pipeline(
        root=root,
        patterns=["*.mp4"],
        max_depth=None,
        selected_stages=[7],
        cfg=cfg,
        cache=None,
        reporter=reporter,
    )

    assert any(key.startswith("timeline") for key in groups.keys())


def test_partial_files_skipped_by_default(tmp_path: Path, reporter: ProgressReporter) -> None:
    root = tmp_path / "partials"
    artifact = root / "movie.part.mp4"
    _touch(artifact, b"A" * 128)

    cfg = PipelineConfig(threads=1, include_partials=False)
    run_pipeline(
        root=root,
        patterns=["*"],
        max_depth=None,
        selected_stages=[1],
        cfg=cfg,
        cache=None,
        reporter=reporter,
    )

    assert reporter.discovery_files == 0
    assert reporter.discovery_artifacts == 1


def test_include_partials_flag_allows_artifacts(tmp_path: Path, reporter: ProgressReporter) -> None:
    root = tmp_path / "partials2"
    artifact = root / "clip.part.mp4"
    _touch(artifact, b"A" * 128)

    cfg = PipelineConfig(threads=1, include_partials=True)
    run_pipeline(
        root=root,
        patterns=["*"],
        max_depth=None,
        selected_stages=[1],
        cfg=cfg,
        cache=None,
        reporter=reporter,
    )

    assert reporter.discovery_files == 1
    assert reporter.discovery_artifacts == 0
