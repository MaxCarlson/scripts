from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import vdedup.gpu_capabilities as gpu_capabilities
import vdedup.gpu_q4 as gpu_q4
import vdedup.phash as phash
from vdedup.gpu_q4 import Q4GResult
from vdedup.pipeline import PipelineConfig, run_pipeline
from vdedup.progress import ProgressReporter


def _touch(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _caps(enabled: bool = True):
    return SimpleNamespace(
        route_enabled=enabled,
        reason_unavailable=None if enabled else "missing gpu",
        device_name="GPU",
        total_vram_bytes=8,
        free_vram_bytes=4,
        compute_capability=(9, 0),
    )


def _run_q4(root: Path, cfg: PipelineConfig):
    return run_pipeline(
        roots=[root],
        patterns=["*.mp4"],
        max_depth=None,
        selected_stages=[4],
        cfg=cfg,
        cache=None,
        reporter=ProgressReporter(enable_dash=False),
    )


def test_gpu_off_uses_cpu_q4(monkeypatch, tmp_path: Path):
    _touch(tmp_path / "a.mp4", b"a")
    _touch(tmp_path / "b.mp4", b"b")
    calls = {"cpu": 0}

    def fake_signature(path, frames=5, gpu=False):
        calls["cpu"] += 1
        return (1, 2, 3)

    monkeypatch.setattr(phash, "compute_phash_signature", fake_signature)
    monkeypatch.setattr(phash, "phash_distance", lambda left, right: 0)

    groups = _run_q4(tmp_path, PipelineConfig(threads=1, gpu_mode="off"))

    assert calls["cpu"] == 2
    assert any(group_id.startswith("phash:") for group_id in groups)


def test_gpu_auto_falls_back_to_cpu_q4_when_q4g_fails(monkeypatch, tmp_path: Path):
    _touch(tmp_path / "a.mp4", b"a")
    _touch(tmp_path / "b.mp4", b"b")
    monkeypatch.setattr(gpu_capabilities, "detect_gpu_capabilities", lambda *args, **kwargs: _caps(True))
    monkeypatch.setattr(gpu_q4, "run_q4g", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(phash, "compute_phash_signature", lambda path, frames=5, gpu=False: (1, 2, 3))
    monkeypatch.setattr(phash, "phash_distance", lambda left, right: 0)

    groups = _run_q4(tmp_path, PipelineConfig(threads=1, gpu_mode="auto"))

    assert any(group_id.startswith("phash:") for group_id in groups)


def test_gpu_on_fails_when_q4g_fails(monkeypatch, tmp_path: Path):
    _touch(tmp_path / "a.mp4", b"a")
    _touch(tmp_path / "b.mp4", b"b")
    monkeypatch.setattr(gpu_capabilities, "detect_gpu_capabilities", lambda *args, **kwargs: _caps(True))
    monkeypatch.setattr(gpu_q4, "run_q4g", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="Q4G failed"):
        _run_q4(tmp_path, PipelineConfig(threads=1, gpu_mode="on"))


def test_gpu_q4g_groups_merge_into_report_groups(monkeypatch, tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _touch(a, b"a")
    _touch(b, b"b")
    monkeypatch.setattr(gpu_capabilities, "detect_gpu_capabilities", lambda *args, **kwargs: _caps(True))

    def fake_q4g(*args, **kwargs):
        result = Q4GResult()
        result.duplicate_groups["gpu-phash:0"] = [a.resolve(), b.resolve()]
        result.group_metadata["gpu-phash:0"] = {
            "method": "gpu-phash",
            "confidence": "verified",
            "review_required": False,
            "actionable": True,
            "match_type": "perceptual_duplicate",
            "evidence": {"backend": "gpu", "verified_edges": []},
        }
        result.signature_count = 2
        return result

    monkeypatch.setattr(gpu_q4, "run_q4g", fake_q4g)

    groups = _run_q4(tmp_path, PipelineConfig(threads=1, gpu_mode="auto"))

    assert "gpu-phash:0" in groups
    assert groups.metadata["gpu-phash:0"]["actionable"] is True
    assert groups.metadata["gpu-phash:0"]["match_type"] == "perceptual_duplicate"


def test_gpu_q4g_candidates_merge_into_candidate_groups(monkeypatch, tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _touch(a, b"a")
    _touch(b, b"b")
    monkeypatch.setattr(gpu_capabilities, "detect_gpu_capabilities", lambda *args, **kwargs: _caps(True))

    def fake_q4g(*args, **kwargs):
        result = Q4GResult()
        result.candidate_groups["visual_candidate:0"] = [a.resolve(), b.resolve()]
        result.candidate_metadata["visual_candidate:0"] = {
            "method": "gpu-visual-candidate",
            "candidate_only": True,
            "actionable": False,
            "review_required": True,
            "match_type": "visual_candidate",
            "recommended_next_stage": "q5",
            "evidence": {"backend": "gpu"},
        }
        result.signature_count = 2
        return result

    monkeypatch.setattr(gpu_q4, "run_q4g", fake_q4g)

    groups = _run_q4(tmp_path, PipelineConfig(threads=1, gpu_mode="auto"))

    assert groups == {}
    assert "visual_candidate:0" in groups.candidate_groups
    assert groups.candidate_metadata["visual_candidate:0"]["actionable"] is False


def test_q4g_never_emits_subset_or_partial_overlap(monkeypatch, tmp_path: Path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _touch(a, b"a")
    _touch(b, b"b")
    monkeypatch.setattr(gpu_capabilities, "detect_gpu_capabilities", lambda *args, **kwargs: _caps(True))

    def fake_q4g(*args, **kwargs):
        result = Q4GResult()
        result.candidate_groups["visual_candidate:0"] = [a.resolve(), b.resolve()]
        result.candidate_metadata["visual_candidate:0"] = {
            "method": "gpu-visual-candidate",
            "candidate_only": True,
            "actionable": False,
            "review_required": True,
            "match_type": "visual_candidate",
            "recommended_next_stage": "q5",
            "evidence": {"backend": "gpu"},
        }
        return result

    monkeypatch.setattr(gpu_q4, "run_q4g", fake_q4g)

    groups = _run_q4(tmp_path, PipelineConfig(threads=1, gpu_mode="auto"))

    assert all(meta.get("match_type") not in {"subset_of_longer", "partial_overlap"} for meta in groups.metadata.values())
    assert all(
        meta.get("match_type") not in {"subset_of_longer", "partial_overlap"}
        for meta in groups.candidate_metadata.values()
    )


def test_q1_candidate_only_safety_remains_unchanged(tmp_path: Path):
    _touch(tmp_path / "a.mp4", b"aaa")
    _touch(tmp_path / "b.mp4", b"bbb")

    groups = run_pipeline(
        roots=[tmp_path],
        patterns=["*.mp4"],
        max_depth=None,
        selected_stages=[1],
        cfg=PipelineConfig(threads=1),
        cache=None,
        reporter=ProgressReporter(enable_dash=False),
    )

    assert groups == {}
    meta = next(iter(groups.candidate_metadata.values()))
    assert meta["candidate_only"] is True
    assert meta["actionable"] is False
