from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import vdedup.pipeline as pipeline_mod
from vdedup.pipeline import PipelineConfig, run_pipeline
from vdedup.progress import ProgressReporter


def _touch(path: Path, content: bytes = b"sample data") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_run_pipeline_supports_multiple_roots(tmp_path: Path) -> None:
    root_a = tmp_path / "root_a"
    root_b = tmp_path / "root_b"

    file_a = root_a / "video_dup.mp4"
    file_b = root_b / "video_dup.mp4"
    _touch(file_a, b"duplicate payload")
    _touch(file_b, b"duplicate payload")

    cfg = PipelineConfig(threads=1)
    reporter = ProgressReporter(enable_dash=False)
    groups = run_pipeline(
        roots=[root_a, root_b],
        patterns=["*.mp4"],
        max_depth=None,
        selected_stages=[1, 2],
        cfg=cfg,
        cache=None,
        reporter=reporter,
    )

    assert groups, "Expected duplicate groups when scanning identical files across roots"
    members = list(groups.values())[0]
    deduped_paths = {m.path.resolve() for m in members}
    assert deduped_paths == {file_a.resolve(), file_b.resolve()}


def test_run_pipeline_q1_size_only_emits_size_groups(tmp_path: Path) -> None:
    root = tmp_path / "size_only"
    same_a = root / "same_a.mp4"
    same_b = root / "same_b.mp4"
    different = root / "different.mp4"
    _touch(same_a, b"abc")
    _touch(same_b, b"xyz")
    _touch(different, b"longer")

    cfg = PipelineConfig(threads=1)
    reporter = ProgressReporter(enable_dash=False)
    groups = run_pipeline(
        roots=[root],
        patterns=["*.mp4"],
        max_depth=None,
        selected_stages=[1],
        cfg=cfg,
        cache=None,
        reporter=reporter,
    )

    assert list(groups.keys()) == ["size:3"]
    assert {m.path.resolve() for m in groups["size:3"]} == {same_a.resolve(), same_b.resolve()}


def test_run_pipeline_q2_hash_only_detects_exact_duplicates_without_q1(tmp_path: Path) -> None:
    root = tmp_path / "hash_only"
    dup_a = root / "dup_a.mp4"
    dup_b = root / "dup_b.mp4"
    same_size_different = root / "same_size_different.mp4"
    _touch(dup_a, b"duplicate")
    _touch(dup_b, b"duplicate")
    _touch(same_size_different, b"different")

    cfg = PipelineConfig(threads=1)
    reporter = ProgressReporter(enable_dash=False)
    groups = run_pipeline(
        roots=[root],
        patterns=["*.mp4"],
        max_depth=None,
        selected_stages=[2],
        cfg=cfg,
        cache=None,
        reporter=reporter,
    )

    assert len(groups) == 1
    group_id, members = next(iter(groups.items()))
    assert group_id.startswith("hash:")
    assert {m.path.resolve() for m in members} == {dup_a.resolve(), dup_b.resolve()}


def test_run_pipeline_max_duplicates_limits_size_only_groups(tmp_path: Path) -> None:
    root = tmp_path / "limited"
    for idx in range(4):
        _touch(root / f"same_{idx}.mp4", bytes([idx]) * 3)

    cfg = PipelineConfig(threads=1, max_duplicates=1)
    reporter = ProgressReporter(enable_dash=False)
    groups = run_pipeline(
        roots=[root],
        patterns=["*.mp4"],
        max_depth=None,
        selected_stages=[1],
        cfg=cfg,
        cache=None,
        reporter=reporter,
    )

    assert len(groups) == 1
    assert sum(max(0, len(members) - 1) for members in groups.values()) >= 1


def test_run_pipeline_sampling_reduces_discovery(tmp_path: Path) -> None:
    root = tmp_path / "samples"
    for idx in range(10):
        _touch(root / f"clip_{idx}.mp4", b"x" * (idx + 1))

    cfg = PipelineConfig(threads=1, sample_ratio=0.4, sample_seed=123)
    reporter = ProgressReporter(enable_dash=False)
    run_pipeline(
        roots=[root],
        patterns=["*.mp4"],
        max_depth=None,
        selected_stages=[1],
        cfg=cfg,
        cache=None,
        reporter=reporter,
    )

    total_files = len(list(root.glob("*.mp4")))
    expected = min(total_files, max(1, int(round(total_files * cfg.sample_ratio))))
    assert reporter.total_files == expected
    assert reporter.discovery_files == expected
    assert any(
        "Sampling" in entry[1] and entry[3] == "SAMPLING"
        for entry in reporter._log_messages  # type: ignore[attr-defined]
    ), "Sampling log entry not recorded"


def test_run_pipeline_sampling_honors_seed(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "seeded"
    for idx in range(6):
        _touch(root / f"video_{idx}.mp4", b"x" * (idx + 5))

    recorded: Dict[str, Any] = {}

    def _recording_random(seed: Any) -> Any:
        recorded["seed"] = seed

        class _Sampler:
            def sample(self, population: List[Path], k: int) -> List[Path]:
                recorded["population"] = list(population)
                recorded["k"] = k
                return list(population)[:k]

        return _Sampler()

    monkeypatch.setattr(pipeline_mod.random, "Random", _recording_random)

    cfg = PipelineConfig(threads=1, sample_ratio=0.5, sample_seed=42)
    reporter = ProgressReporter(enable_dash=False)
    run_pipeline(
        roots=[root],
        patterns=["*.mp4"],
        max_depth=None,
        selected_stages=[1],
        cfg=cfg,
        cache=None,
        reporter=reporter,
    )

    total_files = len(list(root.glob("*.mp4")))
    expected = min(total_files, max(1, int(round(total_files * cfg.sample_ratio))))

    assert recorded["seed"] == 42
    assert recorded["k"] == expected
    assert len(recorded["population"]) == total_files


# ──────────────────────────────────────────
# include_paths tests
# ──────────────────────────────────────────


def test_run_pipeline_include_paths_filters_to_subset(tmp_path: Path) -> None:
    """include_paths limits pipeline to only the specified files."""
    root = tmp_path / "incl"
    a = root / "a.mp4"
    b = root / "b.mp4"
    c = root / "c.mp4"
    _touch(a, b"same_content")
    _touch(b, b"same_content")  # duplicate of a
    _touch(c, b"different_content")

    cfg = PipelineConfig(threads=1)
    reporter = ProgressReporter(enable_dash=False)
    groups = run_pipeline(
        roots=[root],
        patterns=["*.mp4"],
        max_depth=None,
        selected_stages=[2],
        cfg=cfg,
        reporter=reporter,
        include_paths={a.resolve(), b.resolve()},  # exclude c
    )

    # Only a and b were processed; they are exact duplicates → 1 group
    assert reporter.total_files == 2
    assert len(groups) == 1
    members = list(groups.values())[0]
    member_paths = {m.path.resolve() for m in members}
    assert c.resolve() not in member_paths


def test_run_pipeline_include_paths_none_processes_all(tmp_path: Path) -> None:
    """include_paths=None (default) processes all discovered files."""
    root = tmp_path / "all"
    for i in range(3):
        _touch(root / f"v{i}.mp4", b"x" * (i + 1))

    cfg = PipelineConfig(threads=1)
    reporter = ProgressReporter(enable_dash=False)
    run_pipeline(
        roots=[root],
        patterns=["*.mp4"],
        max_depth=None,
        selected_stages=[1],
        cfg=cfg,
        reporter=reporter,
        include_paths=None,
    )

    assert reporter.total_files == 3


def test_run_pipeline_include_paths_empty_set_processes_nothing(tmp_path: Path) -> None:
    """include_paths=set() (empty) means no files pass the filter."""
    root = tmp_path / "empty"
    _touch(root / "a.mp4", b"data")

    cfg = PipelineConfig(threads=1)
    reporter = ProgressReporter(enable_dash=False)
    run_pipeline(
        roots=[root],
        patterns=["*.mp4"],
        max_depth=None,
        selected_stages=[1],
        cfg=cfg,
        reporter=reporter,
        include_paths=set(),
    )

    assert reporter.total_files == 0


# ──────────────────────────────────────────
# Report-seeded scan (_build_seed_include_paths) tests
# ──────────────────────────────────────────


def _write_seed_report(path: Path, keep: Path, losers: List[Path]) -> None:
    """Write a minimal dedup report for seed scan tests."""
    import json

    payload = {
        "summary": {"groups": 1, "losers": len(losers), "size_bytes": 0},
        "groups": {
            "hash:abc": {
                "keep": str(keep),
                "losers": [str(l) for l in losers],
                "method": "hash",
                "evidence": {},
            }
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_seed_include_paths_includes_mandatory(tmp_path: Path) -> None:
    """Seed scan includes all keep+loser paths from the report."""
    from video_dedupe import _build_seed_include_paths
    import logging

    root = tmp_path / "scan_dir"
    root.mkdir()
    keep = root / "keep.mp4"
    loser = root / "loser.mp4"
    other = root / "other.mp4"
    _touch(keep, b"keep")
    _touch(loser, b"loser")
    _touch(other, b"other")

    rp = tmp_path / "report.json"
    _write_seed_report(rp, keep, [loser])

    logger = logging.getLogger("test")
    result = _build_seed_include_paths(
        seed_report=rp,
        parsed_specs=[(root, None)],
        patterns=["*.mp4"],
        exclude_patterns=None,
        seed_random_per_group=0,
        sample_seed=None,
        skip_paths=set(),
        logger=logger,
    )

    assert result is not None
    assert keep.resolve() in result
    assert loser.resolve() in result


def test_seed_include_paths_random_extras_count(tmp_path: Path) -> None:
    """Random extras are N * group_count, capped at available candidates."""
    from video_dedupe import _build_seed_include_paths
    import logging

    root = tmp_path / "scan_dir"
    root.mkdir()
    keep = root / "keep.mp4"
    loser = root / "loser.mp4"
    _touch(keep, b"keep")
    _touch(loser, b"loser")
    # 4 extra candidate files
    extras = [root / f"extra_{i}.mp4" for i in range(4)]
    for f in extras:
        _touch(f, b"x" * extras.index(f))

    rp = tmp_path / "report.json"
    _write_seed_report(rp, keep, [loser])

    logger = logging.getLogger("test")
    result = _build_seed_include_paths(
        seed_report=rp,
        parsed_specs=[(root, None)],
        patterns=["*.mp4"],
        exclude_patterns=None,
        seed_random_per_group=2,  # 2 extras * 1 group = 2
        sample_seed=42,
        skip_paths=set(),
        logger=logger,
    )

    assert result is not None
    # mandatory 2 + random 2 = 4 total
    assert len(result) == 4
    assert keep.resolve() in result
    assert loser.resolve() in result


def test_seed_include_paths_random_extras_deterministic(tmp_path: Path) -> None:
    """Same sample_seed produces the same random extras."""
    from video_dedupe import _build_seed_include_paths
    import logging

    root = tmp_path / "scan_dir"
    root.mkdir()
    keep = root / "keep.mp4"
    loser = root / "loser.mp4"
    _touch(keep, b"keep")
    _touch(loser, b"loser")
    for i in range(10):
        _touch(root / f"extra_{i}.mp4", b"x" * (i + 1))

    rp = tmp_path / "report.json"
    _write_seed_report(rp, keep, [loser])
    logger = logging.getLogger("test")

    result_a = _build_seed_include_paths(
        seed_report=rp,
        parsed_specs=[(root, None)],
        patterns=["*.mp4"],
        exclude_patterns=None,
        seed_random_per_group=3,
        sample_seed=99,
        skip_paths=set(),
        logger=logger,
    )
    result_b = _build_seed_include_paths(
        seed_report=rp,
        parsed_specs=[(root, None)],
        patterns=["*.mp4"],
        exclude_patterns=None,
        seed_random_per_group=3,
        sample_seed=99,
        skip_paths=set(),
        logger=logger,
    )

    assert result_a == result_b


def test_seed_include_paths_caps_at_available(tmp_path: Path) -> None:
    """Random extras are capped when N * groups exceeds available candidates."""
    from video_dedupe import _build_seed_include_paths
    import logging

    root = tmp_path / "scan_dir"
    root.mkdir()
    keep = root / "keep.mp4"
    loser = root / "loser.mp4"
    _touch(keep, b"keep")
    _touch(loser, b"loser")
    # Only 1 candidate extra
    extra = root / "only_extra.mp4"
    _touch(extra, b"extra")

    rp = tmp_path / "report.json"
    _write_seed_report(rp, keep, [loser])
    logger = logging.getLogger("test")

    result = _build_seed_include_paths(
        seed_report=rp,
        parsed_specs=[(root, None)],
        patterns=["*.mp4"],
        exclude_patterns=None,
        seed_random_per_group=100,  # wants 100 but only 1 available
        sample_seed=1,
        skip_paths=set(),
        logger=logger,
    )

    assert result is not None
    # mandatory 2 + capped 1 extra = 3
    assert len(result) == 3
