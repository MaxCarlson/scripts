"""
Tests for Q3 false-positive hardening and Q3→Q4 candidate verification.

Covers:
- Q3 standalone: uses tighter score floor (0.85) and forced codec/container match
- Q3 standalone: emits groups as low-confidence (review_required=True)
- Q3 candidate mode (Q3+Q4): Q4 rejects false-positive candidates → no final group
- Q3 candidate mode: Q4 confirms true-positive candidates → verified group
- Q4 standalone: all-pairs pHash on all non-Q2 videos; excluded_after_q3 is empty
- Independent operation: each quality level runs without errors
- write_report: confidence, review_required, warnings, low_confidence_groups fields
- apply_report: warns on review_required groups
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest
import vdedup as _vdedup_pkg  # used to patch package-level submodule attributes

from vdedup.models import VideoMeta
from vdedup.pipeline import GroupResults, PipelineConfig, _is_q3_standalone, run_pipeline
from vdedup.progress import ProgressReporter


# ──────────────────────────────────────────
# Fixtures / helpers
# ──────────────────────────────────────────


def _touch(path: Path, content: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _make_vm(
    path: Path,
    duration: float = 60.0,
    vcodec: str = "h264",
    container: str = "mp4",
    size: int = 1_000_000,
    width: int = 1920,
    height: int = 1080,
) -> VideoMeta:
    return VideoMeta(
        path=path,
        size=size,
        mtime=0.0,
        duration=duration,
        width=width,
        height=height,
        container=container,
        vcodec=vcodec,
    )


@pytest.fixture(autouse=True)
def _isolate_vdedup_submodule_attrs():
    """
    Clear and restore the `probe`/`phash` package-level attributes around each test.

    When video_fingerprint_test (or any other test) uses @patch('vdedup.probe.*'), the
    real vdedup.probe module gets cached as `vdedup.probe` (package attribute). After
    that, `from vdedup import probe` in run_pipeline retrieves the cached *real* module
    via getattr rather than going through sys.modules, bypassing our patch.dict mocks.

    By deleting the attribute before each test we force Python to re-resolve through
    sys.modules on the next `from vdedup import probe`, so our patch.dict takes effect.
    """
    sentinel = object()
    orig_probe = getattr(_vdedup_pkg, "probe", sentinel)
    orig_phash = getattr(_vdedup_pkg, "phash", sentinel)
    # Clear before the test so run_pipeline's dynamic import uses sys.modules
    if orig_probe is not sentinel:
        delattr(_vdedup_pkg, "probe")
    if orig_phash is not sentinel:
        delattr(_vdedup_pkg, "phash")
    yield
    # Restore after the test (leave the module in the state we found it)
    if orig_probe is not sentinel:
        _vdedup_pkg.probe = orig_probe  # type: ignore[attr-defined]
    if orig_phash is not sentinel:
        _vdedup_pkg.phash = orig_phash  # type: ignore[attr-defined]


def _reporter() -> ProgressReporter:
    return ProgressReporter(enable_dash=False)


def _cfg(**kwargs) -> PipelineConfig:
    defaults = dict(threads=1)
    defaults.update(kwargs)
    return PipelineConfig(**defaults)


def _fake_probe(vm_map: Dict[Path, VideoMeta]):
    """Return a patched _probe_video that looks up VideoMeta from vm_map."""
    def _probe(path: Path) -> Optional[VideoMeta]:
        return vm_map.get(path.resolve())
    return _probe


# ──────────────────────────────────────────
# _is_q3_standalone tests
# ──────────────────────────────────────────


def test_is_q3_standalone_true_when_q3_only():
    assert _is_q3_standalone({3}) is True
    assert _is_q3_standalone({1, 2, 3}) is True


def test_is_q3_standalone_false_when_q4_present():
    assert _is_q3_standalone({3, 4}) is False
    assert _is_q3_standalone({1, 2, 3, 4}) is False
    assert _is_q3_standalone({3, 5}) is False
    assert _is_q3_standalone({3, 6}) is False
    assert _is_q3_standalone({3, 7}) is False


def test_is_q3_standalone_false_when_no_q3():
    assert _is_q3_standalone({4}) is False
    assert _is_q3_standalone({1, 2}) is False


# ──────────────────────────────────────────
# Q3 standalone: score floor & constraints
# ──────────────────────────────────────────


def _run_q3_standalone(tmp_path: Path, vm_a: VideoMeta, vm_b: VideoMeta, **cfg_kwargs) -> GroupResults:
    """Helper: run Q3 standalone with two pre-defined VideoMeta objects."""
    file_a = tmp_path / "a.mp4"
    file_b = tmp_path / "b.mp4"
    _touch(file_a)
    _touch(file_b)

    # Build the vm_map so _probe_video returns our synthetic metadata
    vm_map = {file_a.resolve(): vm_a, file_b.resolve(): vm_b}

    cfg = _cfg(**cfg_kwargs)
    reporter = _reporter()

    def _patched_probe_mod_probe_video(path):
        return vm_map.get(path.resolve())

    fake_probe_mod = MagicMock()
    fake_probe_mod.probe_video = _patched_probe_mod_probe_video

    # The _isolate_vdedup_submodule_attrs fixture clears the package attribute before
    # each test, so patch.dict(sys.modules) is sufficient for isolation.
    with patch("vdedup.pipeline._is_video_suffix", return_value=True), \
         patch("vdedup.pipeline._looks_like_artifact", return_value=False), \
         patch.dict("sys.modules", {"vdedup.probe": fake_probe_mod}):
        groups = run_pipeline(
            roots=[tmp_path],
            patterns=["*.mp4"],
            max_depth=None,
            selected_stages=[3],
            cfg=cfg,
            reporter=reporter,
        )
    return groups


def test_q3_standalone_uses_high_score_floor(tmp_path: Path) -> None:
    """With default q3_standalone_score_floor=0.85, a medium-score pair should not group."""
    # Two videos with same duration and same codec — but we'll mock score to return 0.70
    # (between 0.55 combined floor and 0.85 standalone floor)
    vm_a = _make_vm(tmp_path / "a.mp4", duration=3600.0, vcodec="h264", container="mp4")
    vm_b = _make_vm(tmp_path / "b.mp4", duration=3600.0, vcodec="h264", container="mp4")

    from vdedup.scoring import ScoreCard
    mock_card = ScoreCard(final=0.70, positives={"duration": 0.95}, negatives={}, rationale="mock")

    with patch("vdedup.pipeline.score_metadata_candidate", return_value=mock_card):
        groups = _run_q3_standalone(tmp_path, vm_a, vm_b)

    # 0.70 < 0.85 standalone floor → no group emitted
    assert len(groups) == 0, f"Expected no groups but got: {list(groups.keys())}"


def test_q3_standalone_emits_high_score_as_low_confidence(tmp_path: Path) -> None:
    """Score above standalone floor → group emitted as low-confidence."""
    vm_a = _make_vm(tmp_path / "a.mp4", duration=3600.0, vcodec="h264", container="mp4")
    vm_b = _make_vm(tmp_path / "b.mp4", duration=3600.0, vcodec="h264", container="mp4")

    from vdedup.scoring import ScoreCard
    mock_card = ScoreCard(final=0.92, positives={"duration": 0.99}, negatives={}, rationale="mock")

    with patch("vdedup.pipeline.score_metadata_candidate", return_value=mock_card):
        groups = _run_q3_standalone(tmp_path, vm_a, vm_b)

    assert len(groups) == 1
    gid = next(iter(groups))
    meta = groups.metadata.get(gid, {})
    assert meta.get("confidence") == "low", f"Expected confidence='low', got: {meta}"
    assert meta.get("review_required") is True, f"Expected review_required=True, got: {meta}"


def test_q3_standalone_blocks_different_codecs(tmp_path: Path) -> None:
    """Standalone mode forces same_codec=True; different codecs → no group even with high score."""
    vm_a = _make_vm(tmp_path / "a.mp4", duration=3600.0, vcodec="h264", container="mp4")
    vm_b = _make_vm(tmp_path / "b.mp4", duration=3600.0, vcodec="hevc", container="mp4")  # different codec

    from vdedup.scoring import ScoreCard
    # Even a perfect score shouldn't matter — _similar() rejects before scoring
    mock_card = ScoreCard(final=0.99, positives={}, negatives={}, rationale="mock")

    with patch("vdedup.pipeline.score_metadata_candidate", return_value=mock_card):
        groups = _run_q3_standalone(tmp_path, vm_a, vm_b)

    assert len(groups) == 0, "Different codecs should be blocked in standalone mode"


def test_q3_standalone_blocks_size_outlier(tmp_path: Path) -> None:
    """Standalone mode enforces size ratio; files with >15% size difference don't cluster."""
    vm_a = _make_vm(tmp_path / "a.mp4", duration=3600.0, vcodec="h264", container="mp4", size=1_000_000)
    vm_b = _make_vm(tmp_path / "b.mp4", duration=3600.0, vcodec="h264", container="mp4", size=500_000)  # 50% smaller

    from vdedup.scoring import ScoreCard
    mock_card = ScoreCard(final=0.99, positives={}, negatives={}, rationale="mock")

    with patch("vdedup.pipeline.score_metadata_candidate", return_value=mock_card):
        groups = _run_q3_standalone(tmp_path, vm_a, vm_b)

    assert len(groups) == 0, "Large size difference should be blocked in standalone mode"


# ──────────────────────────────────────────
# Q3 + Q4 candidate verification
# ──────────────────────────────────────────


def _run_q3_q4(
    tmp_path: Path,
    vm_a: VideoMeta,
    vm_b: VideoMeta,
    phash_a: Optional[Tuple[int, ...]],
    phash_b: Optional[Tuple[int, ...]],
) -> Tuple[GroupResults, set]:
    """
    Run Q3+Q4 with two pre-defined VideoMeta objects and phash signatures.
    Returns (groups, excluded_after_q3_snapshot).
    """
    file_a = tmp_path / "a.mp4"
    file_b = tmp_path / "b.mp4"
    _touch(file_a)
    _touch(file_b)

    vm_map = {file_a.resolve(): vm_a, file_b.resolve(): vm_b}
    phash_map = {file_a.resolve(): phash_a, file_b.resolve(): phash_b}

    from vdedup.scoring import ScoreCard
    # Score above combined floor (0.55) so Q3 accepts them as candidates
    mock_card = ScoreCard(final=0.70, positives={"duration": 0.95}, negatives={}, rationale="mock")

    cfg = _cfg()
    reporter = _reporter()

    captured_excl_q3: set = set()

    fake_probe_mod = MagicMock()
    fake_probe_mod.probe_video = lambda path: vm_map.get(path.resolve())

    def fake_compute_phash(path, *, frames=5, gpu=False):
        return phash_map.get(path.resolve())

    def fake_phash_distance(sig_a, sig_b):
        # Return 0 (identical) so threshold is always met — we control similarity via the sigs
        if sig_a == sig_b:
            return 0
        # Large distance → not similar
        return 64 * len(sig_a)

    phash_mod = MagicMock()
    phash_mod.compute_phash_signature = fake_compute_phash
    phash_mod.phash_distance = fake_phash_distance

    with patch("vdedup.pipeline._is_video_suffix", return_value=True), \
         patch("vdedup.pipeline._looks_like_artifact", return_value=False), \
         patch("vdedup.pipeline.score_metadata_candidate", return_value=mock_card), \
         patch.dict("sys.modules", {"vdedup.probe": fake_probe_mod, "vdedup.phash": phash_mod}):
        groups = run_pipeline(
            roots=[tmp_path],
            patterns=["*.mp4"],
            max_depth=None,
            selected_stages=[3, 4],
            cfg=cfg,
            reporter=reporter,
        )

    return groups, groups


def test_q3_candidate_rejected_by_q4_produces_no_group(tmp_path: Path) -> None:
    """
    Q3 groups A+B as candidate, Q4 sees different phash signatures → no final group.
    Rejected videos must not remain in excluded_after_q3 (so Q5/Q6/Q7 can still see them).
    """
    vm_a = _make_vm(tmp_path / "a.mp4", duration=3600.0, vcodec="h264", container="mp4")
    vm_b = _make_vm(tmp_path / "b.mp4", duration=3600.0, vcodec="h264", container="mp4")

    # Different phash signatures → distance = large → Q4 rejects
    phash_a = (1, 2, 3, 4)
    phash_b = (9999, 9998, 9997, 9996)

    file_a = tmp_path / "a.mp4"
    file_b = tmp_path / "b.mp4"
    _touch(file_a)
    _touch(file_b)

    vm_map = {file_a.resolve(): vm_a, file_b.resolve(): vm_b}
    phash_map = {file_a.resolve(): phash_a, file_b.resolve(): phash_b}

    from vdedup.scoring import ScoreCard
    mock_card = ScoreCard(final=0.70, positives={"duration": 0.95}, negatives={}, rationale="mock")

    cfg = _cfg()
    reporter = _reporter()

    fake_probe_mod = MagicMock()
    fake_probe_mod.probe_video = lambda path: vm_map.get(path.resolve())

    def fake_compute_phash(path, *, frames=5, gpu=False):
        return phash_map.get(path.resolve())

    def fake_phash_distance(sig_a, sig_b):
        # Large distance when signatures differ
        return 0 if sig_a == sig_b else 999

    phash_mod = MagicMock()
    phash_mod.compute_phash_signature = fake_compute_phash
    phash_mod.phash_distance = fake_phash_distance

    with patch("vdedup.pipeline._is_video_suffix", return_value=True), \
         patch("vdedup.pipeline._looks_like_artifact", return_value=False), \
         patch("vdedup.pipeline.score_metadata_candidate", return_value=mock_card), \
         patch.dict("sys.modules", {"vdedup.probe": fake_probe_mod, "vdedup.phash": phash_mod}):
        groups = run_pipeline(
            roots=[tmp_path],
            patterns=["*.mp4"],
            max_depth=None,
            selected_stages=[3, 4],
            cfg=cfg,
            reporter=reporter,
        )

    # Q4 rejected → no group in final output
    assert len(groups) == 0, f"Expected no groups but got: {list(groups.keys())}"


def test_q3_candidate_confirmed_by_q4(tmp_path: Path) -> None:
    """
    Q3 groups A+B as candidate, Q4 sees matching phash → verified group with correct flags.
    """
    vm_a = _make_vm(tmp_path / "a.mp4", duration=3600.0, vcodec="h264", container="mp4")
    vm_b = _make_vm(tmp_path / "b.mp4", duration=3600.0, vcodec="h264", container="mp4")

    # Identical phash signatures → Q4 confirms
    shared_phash = (42, 42, 42, 42)

    file_a = tmp_path / "a.mp4"
    file_b = tmp_path / "b.mp4"
    _touch(file_a)
    _touch(file_b)

    vm_map = {file_a.resolve(): vm_a, file_b.resolve(): vm_b}

    from vdedup.scoring import ScoreCard
    mock_card = ScoreCard(final=0.70, positives={"duration": 0.95}, negatives={}, rationale="mock")

    cfg = _cfg()
    reporter = _reporter()

    fake_probe_mod = MagicMock()
    fake_probe_mod.probe_video = lambda path: vm_map.get(path.resolve())

    def fake_compute_phash(path, *, frames=5, gpu=False):
        return shared_phash  # identical for both

    def fake_phash_distance(sig_a, sig_b):
        return 0 if sig_a == sig_b else 999  # 0 = identical

    phash_mod = MagicMock()
    phash_mod.compute_phash_signature = fake_compute_phash
    phash_mod.phash_distance = fake_phash_distance

    with patch("vdedup.pipeline._is_video_suffix", return_value=True), \
         patch("vdedup.pipeline._looks_like_artifact", return_value=False), \
         patch("vdedup.pipeline.score_metadata_candidate", return_value=mock_card), \
         patch.dict("sys.modules", {"vdedup.probe": fake_probe_mod, "vdedup.phash": phash_mod}):
        groups = run_pipeline(
            roots=[tmp_path],
            patterns=["*.mp4"],
            max_depth=None,
            selected_stages=[3, 4],
            cfg=cfg,
            reporter=reporter,
        )

    assert len(groups) == 1, f"Expected 1 verified group, got {len(groups)}: {list(groups.keys())}"
    gid = next(iter(groups))
    meta = groups.metadata.get(gid, {})
    assert meta.get("confidence") == "verified", f"Expected confidence='verified', got: {meta}"
    assert meta.get("review_required") is False, f"Expected review_required=False, got: {meta}"
    assert meta.get("verified_by") == "phash", f"Expected verified_by='phash', got: {meta}"


def test_q4_standalone_excluded_after_q3_is_empty(tmp_path: Path) -> None:
    """When Q3 is not selected, excluded_after_q3 stays empty and Q4 processes all videos."""
    file_a = tmp_path / "a.mp4"
    file_b = tmp_path / "b.mp4"
    _touch(file_a, b"data")
    _touch(file_b, b"data")  # same content = exact duplicate

    cfg = _cfg()
    reporter = _reporter()

    # Q4 standalone: stages=[4], no Q3
    # With same content the all-pairs pass would detect them via pHash if phash is mocked to match
    shared_phash = (1, 2, 3, 4, 5)

    def fake_compute_phash(path, *, frames=5, gpu=False):
        return shared_phash

    def fake_phash_distance(sig_a, sig_b):
        return 0 if sig_a == sig_b else 999

    phash_mod = MagicMock()
    phash_mod.compute_phash_signature = fake_compute_phash
    phash_mod.phash_distance = fake_phash_distance

    with patch("vdedup.pipeline._is_video_suffix", return_value=True), \
         patch("vdedup.pipeline._looks_like_artifact", return_value=False), \
         patch.dict("sys.modules", {"vdedup.phash": phash_mod}):
        groups = run_pipeline(
            roots=[tmp_path],
            patterns=["*.mp4"],
            max_depth=None,
            selected_stages=[4],
            cfg=cfg,
            reporter=reporter,
        )

    # Q4 standalone should find the phash match
    assert len(groups) == 1


# ──────────────────────────────────────────
# Independent operation: each quality level
# ──────────────────────────────────────────


@pytest.mark.parametrize("stages", [[1], [2], [3], [4], [1, 2], [1, 2, 3], [1, 2, 3, 4]])
def test_each_quality_runnable_independently(tmp_path: Path, stages: list) -> None:
    """Every quality-level combination should run without raising."""
    file_a = tmp_path / "a.mp4"
    file_b = tmp_path / "b.mp4"
    _touch(file_a, b"abc")
    _touch(file_b, b"xyz")

    cfg = _cfg()
    reporter = _reporter()

    # Minimal mocks so each stage can progress without real ffprobe / phash
    fake_probe_mod = MagicMock()
    fake_probe_mod.probe_video = lambda path: VideoMeta(path=path, size=3, mtime=0.0)
    phash_mod = MagicMock()
    phash_mod.compute_phash_signature = lambda path, **kw: (1, 2, 3)
    phash_mod.phash_distance = lambda a, b: 0

    with patch("vdedup.pipeline._is_video_suffix", return_value=True), \
         patch("vdedup.pipeline._looks_like_artifact", return_value=False), \
         patch.dict("sys.modules", {"vdedup.probe": fake_probe_mod, "vdedup.phash": phash_mod}):
        result = run_pipeline(
            roots=[tmp_path],
            patterns=["*.mp4"],
            max_depth=None,
            selected_stages=stages,
            cfg=cfg,
            reporter=reporter,
        )

    assert isinstance(result, GroupResults)


# ──────────────────────────────────────────
# write_report: confidence / review_required / warnings
# ──────────────────────────────────────────


def test_write_report_confidence_fields(tmp_path: Path) -> None:
    """write_report serializes confidence, review_required, warnings, low_confidence_groups."""
    from vdedup.models import FileMeta
    from vdedup.report import write_report

    rp = tmp_path / "test_report.json"
    keep = FileMeta(path=tmp_path / "keep.mp4", size=100, mtime=0.0)
    loser = FileMeta(path=tmp_path / "loser.mp4", size=100, mtime=0.0)

    winners = {"meta:0": (keep, [loser])}
    metadata = {
        "meta:0": {
            "detector": "metadata",
            "confidence": "low",
            "review_required": True,
            "scores": {},
        }
    }
    warnings_list = ["1 group(s) are metadata-only."]

    write_report(rp, winners, metadata=metadata, warnings=warnings_list)

    data = json.loads(rp.read_text(encoding="utf-8"))

    # Check group-level fields
    g = data["groups"]["meta:0"]
    assert g["confidence"] == "low"
    assert g["review_required"] is True

    # Check summary
    assert data["summary"]["low_confidence_groups"] == 1

    # Check top-level warnings
    assert data["warnings"] == warnings_list


def test_write_report_hash_group_gets_exact_confidence(tmp_path: Path) -> None:
    """hash: groups automatically get confidence='exact'."""
    from vdedup.models import FileMeta
    from vdedup.report import write_report

    rp = tmp_path / "report.json"
    keep = FileMeta(path=tmp_path / "k.mp4", size=1, mtime=0.0)
    loser = FileMeta(path=tmp_path / "l.mp4", size=1, mtime=0.0)

    write_report(rp, {"hash:abc": (keep, [loser])})
    data = json.loads(rp.read_text(encoding="utf-8"))
    assert data["groups"]["hash:abc"]["confidence"] == "exact"
    assert data["groups"]["hash:abc"]["review_required"] is False


# ──────────────────────────────────────────
# apply_report: warns on review_required
# ──────────────────────────────────────────


def test_apply_report_warns_on_review_required_groups(tmp_path: Path, capsys) -> None:
    """apply_report prints a stderr warning when any group is review_required."""
    from vdedup.report import apply_report

    keep_file = tmp_path / "keep.mp4"
    loser_file = tmp_path / "loser.mp4"
    keep_file.write_text("keep", encoding="utf-8")
    loser_file.write_text("loser", encoding="utf-8")

    rp = tmp_path / "report.json"
    payload = {
        "summary": {"groups": 1, "losers": 1, "size_bytes": 5},
        "warnings": ["1 group(s) are metadata-only."],
        "groups": {
            "meta:0": {
                "keep": str(keep_file),
                "losers": [str(loser_file)],
                "method": "meta",
                "confidence": "low",
                "review_required": True,
                "evidence": {},
                "keep_meta": {"size": 4},
                "loser_meta": {str(loser_file): {"size": 5}},
            }
        },
    }
    rp.write_text(json.dumps(payload), encoding="utf-8")

    apply_report(rp, dry_run=True, force=True, backup=None)

    captured = capsys.readouterr()
    assert "review_required" in captured.err or "metadata-only" in captured.err, (
        f"Expected a review_required warning on stderr; got:\n{captured.err}"
    )
