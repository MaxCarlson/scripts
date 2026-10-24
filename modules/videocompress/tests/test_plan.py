"""
Tests for estimation planning, candidate freezing, and CLI execution.
Follows INTEGRATION_CONTRACTS.md §4, §5 and IMPLEMENTATION_PLAN.md §5, §6.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from videocompress.cli import main
from videocompress.contracts import VideoAsset, VideoEstimationPlan, VideoStream
from videocompress.inventory import InventoryStore
from videocompress.plan import build_estimation_plan, generate_sampling_windows
from videocompress.recipes import get_recipe
from videocompress.workspace import resolve_workspace


def test_sampling_window_generation():
    """Verify deterministic sampling schedules across short, medium, and long durations."""
    # Short duration (< 30s): single window covering duration
    short_win = generate_sampling_windows("sid-short", duration_seconds=15.0, strategy="uniform_3x20")
    assert len(short_win) == 1
    assert short_win[0].start_seconds == 0.0
    assert short_win[0].duration_seconds == 15.0

    # Long duration (e.g. 1000s): 3 windows at 10%, 45%, and 80%
    long_win = generate_sampling_windows("sid-long", duration_seconds=1000.0, strategy="uniform_3x20")
    assert len(long_win) == 3
    assert long_win[0].start_seconds == 100.0
    assert long_win[0].duration_seconds == 20.0
    assert long_win[1].start_seconds == 450.0
    assert long_win[1].duration_seconds == 20.0
    assert long_win[2].start_seconds == 800.0
    assert long_win[2].duration_seconds == 20.0


def test_build_estimation_plan_creates_persisted_artifact(tmp_path: Path):
    """build_estimation_plan must write an immutable plan JSON file into workspace plans directory."""
    media_dir = tmp_path / "videos"
    media_dir.mkdir()
    f1 = media_dir / "movie.mp4"
    f1.write_bytes(b"pseudo_movie_bytes")

    ws = resolve_workspace(media_dir)
    store = InventoryStore(ws.inventory_db)

    # Seed inventory with an eligible asset
    vstream = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="h264",
        width=1920,
        height=1080,
        bit_rate_bps=8_000_000,
        bitrate_provenance="ffprobe_stream",
    )
    asset = VideoAsset(
        source_id="asset-movie-1",
        relative_path="movie.mp4",
        file_bytes=500_000_000,
        container_format="mp4",
        duration_seconds=600.0,
        streams=(vstream,),
    )
    st = f1.stat()
    stat_fp = f"{st.st_mtime_ns}:{st.st_size}"
    store.save_asset(asset, canonical_path=str(f1), stat_fingerprint=stat_fp)

    recipe = get_recipe("av1_nvenc_cq30")
    plan = build_estimation_plan(
        target=media_dir,
        recipes=[recipe],
        workspace_root=ws.root,
        inventory_report=None,  # Will scan inventory
    )

    assert plan.plan_id.startswith("plan-")
    assert len(plan.source_ids) == 1
    assert plan.recipes[0].recipe_id == "av1_nvenc_cq30"
    assert len(plan.sampling_windows) == 3

    # Verify plan artifact on disk
    plan_file = ws.plans_dir / f"{plan.plan_id}.json"
    assert plan_file.exists()
    plan_dict = json.loads(plan_file.read_text(encoding="utf-8"))
    assert plan_dict["plan_id"] == plan.plan_id
    assert plan_dict["recipes"][0]["recipe_id"] == "av1_nvenc_cq30"


def test_cli_plan_and_estimate_subcommands(tmp_path: Path, capsys):
    """Test CLI subcommands `vcompress plan` and `vcompress estimate --tier metadata`."""
    media_dir = tmp_path / "videos"
    media_dir.mkdir()
    f1 = media_dir / "vid1.mp4"
    f1.write_bytes(b"vid1_content")

    ws = resolve_workspace(media_dir)
    store = InventoryStore(ws.inventory_db)

    vstream = VideoStream(
        stream_index=0,
        stream_type="video",
        codec_name="h264",
        width=1920,
        height=1080,
        bit_rate_bps=6_000_000,
        bitrate_provenance="ffprobe_stream",
    )
    astream = VideoStream(
        stream_index=1,
        stream_type="audio",
        codec_name="aac",
        channels=2,
        bit_rate_bps=192_000,
    )
    asset = VideoAsset(
        source_id="asset-cli-test",
        relative_path="vid1.mp4",
        file_bytes=200_000_000,
        container_format="mp4",
        duration_seconds=300.0,
        streams=(vstream, astream),
    )
    st = f1.stat()
    stat_fp = f"{st.st_mtime_ns}:{st.st_size}"
    store.save_asset(asset, canonical_path=str(f1), stat_fingerprint=stat_fp)

    # 1. Run CLI plan
    rc_plan = main(["-N", "plan", "-i", str(media_dir), "-I", str(ws.root.parent), "-e", "av1_nvenc_cq30"])
    assert rc_plan == 0
    captured_plan = capsys.readouterr()
    assert "videocompress Estimation Plan" in captured_plan.out

    # 2. Run CLI estimate human-readable
    rc_est = main([
        "-N",
        "estimate",
        "-i",
        str(media_dir),
        "-I",
        str(ws.root.parent),
        "-P",
        "20.0",
        "-s",
        "10M",
    ])
    assert rc_est == 0
    captured_est = capsys.readouterr()
    assert "videocompress Feasibility & Prediction Report" in captured_est.out
    assert "Notice: Zero encodes performed." in captured_est.out

    # 3. Run CLI estimate with structured JSON output (-J)
    rc_est_json = main([
        "-J",
        "estimate",
        "-i",
        str(media_dir),
        "-I",
        str(ws.root.parent),
        "-P",
        "20.0",
    ])
    assert rc_est_json == 0
    captured_json = capsys.readouterr()
    data = json.loads(captured_json.out)
    assert data["operation"] == "estimate"
    assert data["tier"] == "metadata"
    assert "summary" in data
    assert "per_source_assessments" in data
    assert len(data["per_source_assessments"]) == 1
    assert "calibration_caveat" in data
