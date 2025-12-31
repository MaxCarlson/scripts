#!/usr/bin/env python3
"""
Runs the dedupe pipeline against the generated media dataset and reports accuracy metrics.

Usage:
    python modules/vdedup/tests/evaluate_media_dataset.py \
        --dataset modules/vdedup/tests/media_dataset

Requires that `generate_media_dataset.py` has been executed beforehand.
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from vdedup.pipeline import PipelineConfig, run_pipeline
from vdedup.progress import ProgressReporter


def _pairs_from_groups(group_members: Dict[str, List[Path]]) -> Set[frozenset[Path]]:
    pairs: Set[frozenset[Path]] = set()
    for members in group_members.values():
        for a, b in itertools.combinations(members, 2):
            pairs.add(frozenset((a.resolve(), b.resolve())))
    return pairs


def load_manifest(manifest_path: Path) -> Tuple[Dict[str, List[Path]], Path, Dict[str, object]]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset_dir = manifest_path.parent
    groups: Dict[str, List[Path]] = {}
    for entry in data.get("groups", []):
        gid = entry["id"]
        members = []
        for meta in entry.get("members", []):
            members.append(Path(meta["path"]).expanduser().resolve())
        groups[gid] = members
    for neg in data.get("negatives", []):
        path = Path(neg["path"]).expanduser().resolve()
        groups[path.stem] = [path]
    return groups, dataset_dir, data


def evaluate_manifest(manifest_path: Path, cfg: PipelineConfig) -> Dict[str, object]:
    groups, base_dir, manifest_data = load_manifest(manifest_path)
    reporter = ProgressReporter(enable_dash=False)
    results = run_pipeline(
        roots=[base_dir],
        patterns=["*.mp4"],
        max_depth=None,
        selected_stages=[1, 2, 3, 4],
        cfg=cfg,
        cache=None,
        reporter=reporter,
    )
    expected_pairs = _pairs_from_groups(groups)
    actual_groups_paths: Dict[str, List[Path]] = {}
    for gid, members in results.items():
        actual_groups_paths[gid] = [Path(m.path).resolve() for m in members]
    actual_pairs = _pairs_from_groups(actual_groups_paths)
    tp = len(expected_pairs & actual_pairs)
    fn = len(expected_pairs - actual_pairs)
    fp = len(actual_pairs - expected_pairs)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    result = {
        "manifest": manifest_path,
        "seed": manifest_data.get("seed"),
        "queries": manifest_data.get("queries", []),
        "expected_pairs": len(expected_pairs),
        "actual_pairs": len(actual_pairs),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "false_positive_pairs": sorted(actual_pairs - expected_pairs),
        "missed_pairs": sorted(expected_pairs - actual_pairs),
    }
    return result


def _resolve_manifest_paths(dataset_path: Path) -> List[Path]:
    dataset_path = dataset_path.expanduser().resolve()
    manifests: List[Path] = []
    if dataset_path.is_file():
        if dataset_path.name == "dataset_manifest.json":
            manifests.append(dataset_path)
        else:
            raise FileNotFoundError(f"{dataset_path} is not a dataset_manifest.json file.")
        return manifests

    candidate = dataset_path / "dataset_manifest.json"
    if candidate.exists():
        manifests.append(candidate)
    for child in sorted(dataset_path.glob("seed_*")):
        man = child / "dataset_manifest.json"
        if man.exists():
            manifests.append(man)
    if not manifests:
        raise FileNotFoundError(
            f"No dataset_manifest.json found under {dataset_path}. "
            "Run generate_media_dataset.py first."
        )
    return manifests


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate pipeline accuracy on the media dataset.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).resolve().parent / "media_dataset",
        help="Path to dataset directory (default: tests/media_dataset)",
    )
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--q4-threshold", type=int, default=14)
    parser.add_argument("--metadata-score", type=float, default=0.6)
    args = parser.parse_args()
    cfg = PipelineConfig(
        threads=args.threads,
        subset_detect=True,
        subset_min_ratio=0.08,
        subset_frame_threshold=8,
        phash_frames=10,
        phash_threshold=args.q4_threshold,
        duration_tolerance=1.0,
        metadata_score_floor=args.metadata_score,
        same_res=False,
        same_codec=False,
        same_container=False,
    )
    manifests = _resolve_manifest_paths(args.dataset)
    for manifest in manifests:
        stats = evaluate_manifest(manifest, cfg)
        label = f"seed {stats['seed']}" if stats.get("seed") is not None else manifest.parent.name
        print(f"\n=== Evaluation for {label} ({manifest.parent}) ===")
        print("Expected pairs:", stats["expected_pairs"])
        print("Actual pairs  :", stats["actual_pairs"])
        print(f"True positives: {stats['tp']}")
        print(f"False positives: {stats['fp']}")
        print(f"False negatives: {stats['fn']}")
        print(f"Precision: {stats['precision']:.3f}")
        print(f"Recall   : {stats['recall']:.3f}")
        if stats["false_positive_pairs"]:
            print("\nFalse-positive pairs:")
            for pair in stats["false_positive_pairs"]:
                a, b = sorted(pair)
                print("  ", a, "<->", b)
        if stats["missed_pairs"]:
            print("\nMissed pairs:")
            for pair in stats["missed_pairs"]:
                a, b = sorted(pair)
                print("  ", a, "<->", b)


if __name__ == "__main__":
    main()
