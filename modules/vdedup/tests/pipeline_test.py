from __future__ import annotations

from pathlib import Path

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
