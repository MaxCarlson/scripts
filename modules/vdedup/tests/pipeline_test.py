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
