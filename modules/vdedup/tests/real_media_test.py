from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

from vdedup.pipeline import PipelineConfig, run_pipeline
from vdedup.progress import ProgressReporter

DATASET_ROOT = Path(__file__).resolve().parent / "media_dataset"
ENV_DATASET = os.environ.get("VDEDUP_REAL_MEDIA_DATASET") or os.environ.get("VDEDUP_MEDIA_DATASET")
RUN_REAL_MEDIA = os.environ.get("VDEDUP_REAL_MEDIA_TESTS") == "1"
MIN_SAMPLE_BYTES = 1_000_000


def _candidate_manifest_paths() -> List[Path]:
    bases: List[Path] = []
    if ENV_DATASET:
        bases.append(Path(ENV_DATASET).expanduser().resolve())
    bases.append(DATASET_ROOT)
    manifests: List[Path] = []
    for base in bases:
        if base.is_file():
            if base.name == "dataset_manifest.json":
                manifests.append(base)
            continue
        if not base.exists():
            continue
        direct = base / "dataset_manifest.json"
        if direct.exists():
            manifests.append(direct)
        for child in sorted(base.glob("seed_*")):
            cand = child / "dataset_manifest.json"
            if cand.exists():
                manifests.append(cand)
    return manifests


def _load_manifest() -> Optional[Tuple[Path, Dict[str, object]]]:
    for manifest_path in _candidate_manifest_paths():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        return manifest_path.parent, data
    return None


DATASET_INFO = _load_manifest()
pytestmark = pytest.mark.skipif(
    (not RUN_REAL_MEDIA) or DATASET_INFO is None,
    reason=(
        "Set VDEDUP_REAL_MEDIA_TESTS=1 and generate data via "
        "`python modules/vdedup/tests/generate_media_dataset.py`."
    ),
)


def _ensure_files_present(entries: List[Dict[str, object]]) -> None:
    missing: List[str] = []
    for entry in entries:
        path = Path(str(entry["path"])).expanduser().resolve()
        if not path.exists() or path.stat().st_size < MIN_SAMPLE_BYTES:
            missing.append(str(path))
    if missing:
        pytest.skip(f"Dataset incomplete. Missing samples: {missing}")


def _pick_group(manifest: Dict[str, object]) -> Dict[str, object]:
    for group in manifest.get("groups", []):
        members = group.get("members", [])
        if len(members) >= 2:
            return group
    raise pytest.SkipTest("No suitable group with multiple members found in manifest.")


def _choose_member(entries: List[Dict[str, object]], predicate) -> Optional[Path]:
    for entry in entries:
        if predicate(entry):
            return Path(str(entry["path"])).expanduser().resolve()
    return None


def _find_group_containing(groups, paths) -> Optional[Tuple[str, List[Path]]]:
    targets = {Path(p).resolve() for p in paths}
    for gid, members in groups.items():
        member_paths = {Path(m.path).resolve() for m in members}
        if targets.issubset(member_paths):
            return gid, list(member_paths)
    return None


def _score_payload_has_path(payload: Dict[str, object], file_path: Path) -> bool:
    target = file_path.resolve()
    for key in payload.keys():
        try:
            if Path(key).resolve() == target:
                return True
        except Exception:
            continue
    return False


def test_real_media_pipeline_groups_expected_files() -> None:
    assert DATASET_INFO is not None  # for type checkers
    dataset_dir, manifest = DATASET_INFO
    target_group = _pick_group(manifest)
    members = target_group.get("members", [])
    _ensure_files_present(members)

    master = _choose_member(members, lambda m: m.get("role") == "master")
    assert master, "Dataset group missing master variant"
    variant = _choose_member(
        members,
        lambda m: m.get("role") not in {"master"} and not str(m.get("role", "")).startswith("subset"),
    )
    assert variant, "No transcode/downscale variant available for testing"
    subset_clip = _choose_member(members, lambda m: str(m.get("role", "")).startswith("subset"))
    assert subset_clip, "No subset clip generated for dataset"

    negatives = manifest.get("negatives", [])
    assert negatives, "Dataset missing synthetic negative clip"
    different = Path(str(negatives[0]["path"])).expanduser().resolve()
    assert different.exists(), "Negative clip missing on disk"

    reporter = ProgressReporter(enable_dash=False)
    cfg = PipelineConfig(
        threads=1,
        subset_detect=True,
        subset_min_ratio=0.08,
        subset_frame_threshold=8,
        phash_frames=10,
        phash_threshold=14,
        duration_tolerance=1.0,
        metadata_score_floor=0.6,
        same_res=False,
        same_codec=False,
        same_container=False,
    )
    groups = run_pipeline(
        roots=[dataset_dir],
        patterns=["*.mp4"],
        max_depth=None,
        selected_stages=[1, 2, 3, 4],
        cfg=cfg,
        cache=None,
        reporter=reporter,
    )

    metadata_group = _find_group_containing(groups, [master, variant])
    assert metadata_group is not None, "Variant was not grouped with master."
    meta_gid, _ = metadata_group
    meta_payload = groups.metadata.get(meta_gid, {})
    assert meta_payload.get("detector") in {"metadata", "subset-phash", "phash"}
    meta_scores = meta_payload.get("scores") or {}
    assert _score_payload_has_path(meta_scores, master)
    assert _score_payload_has_path(meta_scores, variant)

    subset_group = _find_group_containing(groups, [master, subset_clip])
    assert subset_group is not None, "Subset clip was not matched to master."
    subset_gid, _ = subset_group
    subset_payload = groups.metadata.get(subset_gid, {})
    assert subset_payload.get("detector") in {"subset-phash", "metadata"}

    for members in groups.values():
        member_paths = {Path(m.path).resolve() for m in members}
        assert different not in member_paths, f"Negative clip {different} should not be grouped"
