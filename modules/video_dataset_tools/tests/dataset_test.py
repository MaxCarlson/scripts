import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Ensure module import path
sys.path.append(str(Path(__file__).resolve().parents[2].parent))

from video_dataset_tools.dataset import (
    ProgressTracker,
    RandomPlan,
    build_truth_manifest,
    discover_random_urls,
    create_random_variants,
    create_variants,
    generate_dataset,
    parse_trim,
    prepare_keys_from_urls,
    write_mapping_files,
    _plan_random_variants,
)


def _touch(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")


@pytest.fixture()
def dummy_src(tmp_path):
    src = tmp_path / "source.mp4"
    src.write_text("src")
    return src


@pytest.fixture()
def fake_transforms(monkeypatch):
    """Patch transformation helpers to just create output files."""

    created = []

    def _make_out(*args, **kwargs):
        out = args[1]
        _touch(out)
        created.append(out)

    monkeypatch.setattr("video_dataset_tools.dataset.trim_video", _make_out)
    monkeypatch.setattr("video_dataset_tools.dataset.scale_video", _make_out)
    monkeypatch.setattr("video_dataset_tools.dataset.change_audio_bitrate", _make_out)
    monkeypatch.setattr("video_dataset_tools.dataset.remove_audio", _make_out)
    monkeypatch.setattr("video_dataset_tools.dataset.change_video_bitrate", _make_out)
    return created


def test_create_variants_produces_expected_outputs(dummy_src, tmp_path, fake_transforms):
    out_dir = tmp_path / "variants"
    produced = create_variants("k1", dummy_src, out_dir)

    expected_names = {
        "k1_clip15.mp4",
        "k1_clip10min.mp4",
        "k1_clip36_45.mp4",
        "k1_clip1023_7834.mp4",
        "k1_360p.mp4",
        "k1_240p.mp4",
        "k1_64k.mp4",
        "k1_32k.mp4",
        "k1_noaudio.mp4",
        "k1_1M.mp4",
        "k1_crf30.mp4",
        "k1_renamed.mp4",
    }
    assert {p.name for p in produced} == expected_names
    for p in produced:
        assert p.exists()


def test_plan_random_variants_deterministic():
    plan = RandomPlan(seed=123, min_variants=2, max_variants=4, overlap_prob=0.9)
    recipes_first = _plan_random_variants("keyA", plan)
    recipes_second = _plan_random_variants("keyA", plan)
    assert len(recipes_first) == len(recipes_second) >= 2
    # Each run with same seed/key should match
    assert [sorted(r.keys()) for r in recipes_first] == [sorted(r.keys()) for r in recipes_second]


def test_create_random_variants_matches_plan(dummy_src, tmp_path, monkeypatch):
    plan = RandomPlan(seed=5, min_variants=2, max_variants=5, overlap_prob=0.8)
    recipes = _plan_random_variants("keyX", plan)
    calls = []

    def fake_render(src, dest_path, **kwargs):
        _touch(dest_path)
        calls.append((dest_path, kwargs))

    monkeypatch.setattr("video_dataset_tools.dataset._render_combo_variant", fake_render)
    outputs = create_random_variants("keyX", dummy_src, tmp_path, plan=plan, ffmpeg_mode="cuda", flat_variants=True)

    assert len(outputs) == len(recipes)
    assert all(o.exists() for o in outputs)
    assert all(kwargs["mode"] == "cuda" for _, kwargs in calls)


def test_prepare_keys_from_urls_and_mapping(tmp_path):
    urls = ["u1", "u2", "u3"]
    keys, mapping = prepare_keys_from_urls(urls, num_masters=2, seed=1, shuffle_urls=True)
    assert len(keys) == 2
    assert set(mapping.keys()) == set(keys)

    mapping_path = tmp_path / "mapping.txt"
    id_map_path = tmp_path / "id_map.json"
    write_mapping_files(keys, mapping, mapping_path, id_map_path)
    assert mapping_path.read_text(encoding="utf-8").strip().splitlines() == keys
    stored = json.loads(id_map_path.read_text(encoding="utf-8"))
    assert stored == mapping


def test_discover_random_urls_uses_seed_and_parses(monkeypatch):
    payload = """
{"id": "id1"}
{"id": "id2"}
"""

    def fake_run(cmd, stdout=None, stderr=None):
        return SimpleNamespace(returncode=0, stdout=payload.encode(), stderr=b"")

    monkeypatch.setattr("video_dataset_tools.dataset.subprocess.run", fake_run)

    urls = discover_random_urls(2, seed=1, per_query=2)
    assert urls == [
        "https://www.youtube.com/watch?v=id1",
        "https://www.youtube.com/watch?v=id2",
    ]


def test_parse_trim_formats_and_validation():
    spec = parse_trim("1.5:3")
    assert spec.name.startswith("clip_")
    assert spec.start == 1.5 and spec.duration == 3

    named = parse_trim("seg:2:4")
    assert named.name == "seg" and named.start == 2 and named.duration == 4

    with pytest.raises(argparse.ArgumentTypeError):
        parse_trim("bad")


def test_build_truth_manifest_handles_layouts(tmp_path):
    out = tmp_path
    orig = out / "original" / "k1.mp4"
    orig2 = out / "original" / "k2.mp4"
    flat = out / "variants" / "k1_clip.mp4"
    per_key = out / "variants" / "k2" / "k2_clip.mp4"
    for p in (orig, orig2, flat, per_key):
        _touch(p)

    manifest = build_truth_manifest(out)
    assert "k1" in manifest and "k2" in manifest
    assert Path(manifest["k1"]["original"]).name == "k1.mp4"
    assert any(Path(v).name.startswith("k1_clip") for v in manifest["k1"]["variants"])
    assert any(Path(v).name.startswith("k2_clip") for v in manifest["k2"]["variants"])


class DummyBoard:
    def __init__(self):
        self.added = []
        self.updated = []

    def add_row(self, name, *cells):
        self.added.append((name, cells))

    def update(self, line, stat, value):
        self.updated.append((line, stat, value))


def test_progress_tracker_updates_board():
    board = DummyBoard()
    tracker = ProgressTracker(total_keys=3, board=board)
    tracker.set_total(3)
    tracker.on_start("k1")
    tracker.on_download()
    tracker.on_variants(2, 1)
    tracker.on_error()

    updated_stats = {item[1] for item in board.updated}
    assert {"keys", "downloaded", "variants", "errors", "rate", "elapsed"}.issubset(updated_stats)


def test_generate_dataset_uses_stubs(monkeypatch, tmp_path):
    keys = ["k1", "k2"]
    id_map = {"k1": "url1", "k2": "url2"}

    def fake_download(youtube_id, dest_dir, key):
        path = dest_dir / f"{key}.mp4"
        _touch(path)
        return path

    def fake_create_variants(key, src_path, variants_dir, **kwargs):
        out = variants_dir / f"{key}" / f"{key}_v1.mp4"
        _touch(out)
        return [out]

    def fake_random_variants(key, src_path, variants_dir, **kwargs):
        out = variants_dir / f"{key}" / f"{key}_rand.mp4"
        _touch(out)
        return [out]

    tracker_calls = []

    class Tracker:
        def __init__(self):
            self.total = 0

        def set_total(self, total):
            self.total = total
            tracker_calls.append("total")

        def on_start(self, key):
            tracker_calls.append("start")

        def on_download(self):
            tracker_calls.append("dl")

        def on_variants(self, det, rand):
            tracker_calls.append((det, rand))

        def on_error(self):
            tracker_calls.append("err")

    monkeypatch.setattr("video_dataset_tools.dataset.download_video", fake_download)
    monkeypatch.setattr("video_dataset_tools.dataset.create_variants", fake_create_variants)
    monkeypatch.setattr("video_dataset_tools.dataset.create_random_variants", fake_random_variants)

    manifest = generate_dataset(
        keys,
        id_map,
        tmp_path,
        skip_download=False,
        random_plan=RandomPlan(seed=1, min_variants=1, max_variants=1, overlap_prob=0.5),
        workers=1,
        ffmpeg_mode="cpu",
        progress=Tracker(),
    )

    assert set(manifest.keys()) == set(keys)
    for key in keys:
        assert Path(manifest[key]["original"]).name == f"{key}.mp4"
        assert any("v1" in v or "rand" in v for v in manifest[key]["variants"])
    assert "total" in tracker_calls
