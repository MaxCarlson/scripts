"""
Pytest module to validate the `vdedup` pipeline on the generated dataset.

This test discovers all original and variant videos under a given dataset
directory, infers the ground‑truth grouping based on the key (filename
prefix or parent directory) and runs the vdedup pipeline to obtain
duplicate groups.  It then asserts that:

* All variants of the same key are grouped together by vdedup.
* No group contains files from different keys.

To execute this test, ensure that the dataset has been generated via
`generate_videos.py` and that the `vdedup` code is importable.  The test
assumes that the repository root has been added to `sys.path` (Pytest
usually does this automatically for in‑repo modules).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Iterable, List, Set

import pytest

# Attempt to import the pipeline from the repository.  Depending on how
# pytest is invoked, the repository root may not be on sys.path.  Add
# `scripts` parent directory relative to this file to ensure imports work.
_this_file = Path(__file__).resolve()
repo_root = _this_file.parent.parent.parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

try:
    from modules.vdedup.pipeline import PipelineConfig, run_pipeline  # type: ignore
except Exception as exc:  # pragma: no cover
    pytest.skip(f"Could not import vdedup pipeline: {exc}")


def discover_dataset_files(data_dir: Path) -> List[Path]:
    """Recursively collect all video files in the dataset directory."""
    return [p for p in data_dir.rglob("*") if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".avi", ".mov"}]


def infer_key_from_path(path: Path) -> str:
    """
    Infer the grouping key for a given file path.  For original files, the
    key is the stem (filename without extension).  For variant files,
    assume they are stored under `variants/<key>/` and return the parent
    directory name.  This logic should match the layout produced by
    `generate_videos.py`.
    """
    parts = path.parts
    # If the file is under variants/<key>/, use that directory
    if "variants" in parts:
        try:
            idx = parts.index("variants")
            return parts[idx + 1]
        except (ValueError, IndexError):
            return path.stem.split("_")[0]
    # Otherwise use filename stem
    return path.stem.split("_")[0]


def build_ground_truth(file_paths: Iterable[Path]) -> Dict[str, Set[str]]:
    """Build a mapping from key to set of file paths (as strings)."""
    gt: Dict[str, Set[str]] = {}
    for p in file_paths:
        key = infer_key_from_path(p)
        gt.setdefault(key, set()).add(str(p))
    return gt


def extract_pipeline_groups(groups: Iterable) -> List[Set[str]]:
    """
    Convert the pipeline output into a list of sets of file paths.  The
    vdedup pipeline returns a sequence of group objects; each group is
    expected to have a `files` or `paths` attribute or be an iterable of
    file paths.  This helper normalizes the structure by iterating over
    each group and converting contained items to strings.
    """
    normalized: List[Set[str]] = []
    for group in groups:
        # Attempt to obtain files from attributes or by iteration
        if hasattr(group, "paths"):
            items = getattr(group, "paths")  # type: ignore
        elif hasattr(group, "files"):
            items = getattr(group, "files")  # type: ignore
        else:
            # Fallback: assume group itself is iterable of Paths
            items = group
        normalized.append({str(p) for p in items})
    return normalized


@pytest.mark.skipif(
    not hasattr(sys.modules.get("modules.vdedup.pipeline"), "run_pipeline"),
    reason="vdedup pipeline is not available",
)
def test_vdedup_dataset(tmp_path: Path) -> None:
    """
    End‑to‑end test that runs the vdedup pipeline on the dataset and checks
    grouping accuracy.  This test uses the default pipeline configuration
    with subset detection and audio fingerprinting enabled.
    """
    # Dataset directory relative to the repository root
    data_dir = repo_root / "data"
    assert data_dir.exists(), f"Dataset directory {data_dir} does not exist"
    # Discover all files
    files = discover_dataset_files(data_dir)
    assert files, "No dataset files found. Generate the dataset first."
    # Build ground truth mapping: key -> set of files
    ground_truth = build_ground_truth(files)
    # Run the pipeline; we pass an iterator of file paths
    config = PipelineConfig()  # Use defaults; enable subset detection by default
    # Some versions of PipelineConfig may require explicit parameters; adjust as needed
    groups = run_pipeline(config, files)  # type: ignore[call-arg]
    pipeline_groups = extract_pipeline_groups(groups)
    # Build mapping from pipeline group to keys
    group_keys: List[Set[str]] = []
    for g in pipeline_groups:
        keys = {infer_key_from_path(Path(p)) for p in g}
        group_keys.append(keys)
    # 1. Check that each ground truth set is contained within some pipeline group
    for key, expected_files in ground_truth.items():
        # Find pipeline groups that cover this key
        matching = [g for g in pipeline_groups if expected_files.issubset(g)]
        assert matching, f"No pipeline group contains all variants of key {key}"
    # 2. Ensure no pipeline group mixes keys
    for keys in group_keys:
        assert len(keys) == 1, f"Pipeline group mixes keys: {keys}"