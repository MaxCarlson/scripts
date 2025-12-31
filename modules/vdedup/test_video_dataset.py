"""
Tests for the shared dataset toolkit used by vdedup.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pytest

import modules.video_dataset_tools.dataset as vd


def test_load_keys(tmp_path: Path) -> None:
    """Ensure load_keys reads lines and ignores blanks."""
    mapping_file = tmp_path / "mapping.txt"
    mapping_file.write_text("a\n\n b \n c\n", encoding="utf-8")
    keys = vd.load_keys(mapping_file)
    assert keys == ["a", "b", "c"]


def test_load_id_map(tmp_path: Path) -> None:
    """Ensure load_id_map reads a JSON dict and coerces to strings."""
    id_map_file = tmp_path / "id_map.json"
    json.dump({"x": 123, 1: "abc"}, id_map_file.open("w", encoding="utf-8"))
    id_map = vd.load_id_map(id_map_file)
    # Keys and values should be strings
    assert id_map == {"x": "123", "1": "abc"}


def test_generate_dataset_invokes_download_and_variants(monkeypatch, tmp_path: Path) -> None:
    """
    Verify that generate_dataset calls download_video for each key (unless
    skip_download is True) and create_variants for each downloaded file.  Use
    monkeypatch to replace these functions with stubs that record calls.
    """
    # Prepare dummy keys and id map
    keys: List[str] = ["k1", "k2"]
    id_map: Dict[str, str] = {"k1": "vid1", "k2": "vid2"}
    output_dir = tmp_path / "out"
    # Record calls
    downloaded: List[str] = []
    variants: List[str] = []

    def fake_download(video_id: str, dest: Path, key: str) -> Path:
        downloaded.append(key)
        # Create a dummy file to simulate download
        dest.mkdir(parents=True, exist_ok=True)
        f = dest / f"{key}.mp4"
        f.write_text("dummy", encoding="utf-8")
        return f

    def fake_create_variants(key: str, src_path: Path, dest: Path, **kwargs) -> None:
        variants.append(key)
        # Create a dummy variant directory
        out_dir = dest / key
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{key}_renamed.mp4").write_text("variant", encoding="utf-8")

    monkeypatch.setattr(vd, "download_video", fake_download)
    monkeypatch.setattr(vd, "create_variants", fake_create_variants)
    # Execute dataset generation
    vd.generate_dataset(keys, id_map, output_dir, skip_download=False, write_manifest=False)
    # Both keys should have been downloaded and variants created
    assert sorted(downloaded) == ["k1", "k2"]
    assert sorted(variants) == ["k1", "k2"]
    # Now test skip_download: no downloads should occur, but variants should be created
    downloaded.clear()
    variants.clear()
    # Create existing originals
    orig_dir = output_dir / "original"
    orig_dir.mkdir(parents=True, exist_ok=True)
    for key in keys:
        (orig_dir / f"{key}.mp4").write_text("existing", encoding="utf-8")
    vd.generate_dataset(keys, id_map, output_dir, skip_download=True, write_manifest=False)
    assert downloaded == []
    assert sorted(variants) == ["k1", "k2"]


def test_truth_manifest_roundtrip(tmp_path: Path) -> None:
    """Ensure manifest builder captures originals and variants relative paths."""

    output_dir = tmp_path / "data"
    originals = output_dir / "original"
    variants = output_dir / "variants" / "k1"
    originals.mkdir(parents=True, exist_ok=True)
    variants.mkdir(parents=True, exist_ok=True)
    (originals / "k1.mp4").write_text("orig", encoding="utf-8")
    (variants / "k1_clip15.mp4").write_text("v1", encoding="utf-8")
    (variants / "k1_360p.mp4").write_text("v2", encoding="utf-8")

    manifest = vd.build_truth_manifest(output_dir)
    truth_path = vd.write_truth_manifest(manifest, output_dir)

    # Validate manifest content
    payload = json.loads(truth_path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert Path(payload["keys"]["k1"]["original"]).as_posix() == "original/k1.mp4"
    assert {Path(v).as_posix() for v in payload["keys"]["k1"]["variants"]} == {
        "variants/k1/k1_clip15.mp4",
        "variants/k1/k1_360p.mp4",
    }