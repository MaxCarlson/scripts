"""
Tests for videocompress CLI parser, flag conventions, and operations.
Follows scripts repository rules: every user-facing argument has short and long forms.
"""

from __future__ import annotations

import argparse
import pytest

from videocompress.cli import build_parser, main


def test_build_parser_subcommands():
    parser = build_parser()
    expected_ops = {
        "capabilities",
        "inventory",
        "plan",
        "estimate",
        "analyze",
        "compare",
        "preview",
        "apply",
        "recover",
    }
    # Inspect registered subcommands
    subparser_actions = [
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    ]
    assert len(subparser_actions) == 1
    registered_ops = set(subparser_actions[0].choices.keys())
    assert expected_ops == registered_ops


def test_every_optional_flag_has_short_and_long_form():
    parser = build_parser()
    subparser_actions = [
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    ]
    subparsers_dict = subparser_actions[0].choices

    # Check top-level optional flags (excluding help)
    for opt in parser._actions:
        if opt.option_strings and "--help" not in opt.option_strings:
            short_opts = [s for s in opt.option_strings if len(s) == 2 and s.startswith("-")]
            long_opts = [s for s in opt.option_strings if s.startswith("--")]
            assert short_opts, f"Top-level option {opt.option_strings} lacks short form -X"
            assert long_opts, f"Top-level option {opt.option_strings} lacks long form --name"

    # Check each subcommand's optional flags
    for name, subp in subparsers_dict.items():
        for opt in subp._actions:
            if opt.option_strings and "--help" not in opt.option_strings:
                short_opts = [s for s in opt.option_strings if len(s) == 2 and s.startswith("-")]
                long_opts = [s for s in opt.option_strings if s.startswith("--")]
                assert short_opts, f"Subcommand '{name}' option {opt.option_strings} lacks short form -X"
                assert long_opts, f"Subcommand '{name}' option {opt.option_strings} lacks long form --name"


def test_inventory_parser_arguments():
    parser = build_parser()
    args = parser.parse_args([
        "inventory",
        "-i", "D:/Media",
        "-I", "E:/Workspace",
        "-B", "4M",
        "-R", "1920x1080",
        "-d", "probe",
    ])
    assert args.operation == "inventory"
    assert args.input_target == "D:/Media"
    assert args.workspace_root == "E:/Workspace"
    assert args.min_video_bitrate == "4M"
    assert args.min_resolution == "1920x1080"
    assert args.inventory_depth == "probe"


def test_estimate_parser_arguments():
    parser = build_parser()
    args = parser.parse_args([
        "estimate",
        "-i", "D:/Media",
        "-r", "plan-001",
        "-E", "sampled",
        "-M", "10m",
        "-T", "5",
    ])
    assert args.operation == "estimate"
    assert args.plan_id == "plan-001"
    assert args.estimate_tier == "sampled"
    assert args.max_time == "10m"
    assert args.max_trials == 5


def test_apply_parser_arguments():
    parser = build_parser()
    args = parser.parse_args([
        "apply",
        "-i", "D:/Media",
        "-r", "plan-001",
        "-w",
        "-L",
        "-o", "D:/Optimized",
    ])
    assert args.operation == "apply"
    assert args.allow_write is True
    assert args.allow_lossy is True
    assert args.output_root == "D:/Optimized"


def test_main_dispatch_json(capsys):
    ret = main(["capabilities", "-J"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "ffmpeg_available" in captured.out


def test_main_inventory_dispatch(tmp_path, capsys):
    media = tmp_path / "media"
    media.mkdir()
    (media / "v1.mp4").write_bytes(b"content")

    ret = main(["inventory", "-i", str(media), "-d", "files", "-J"])
    assert ret == 0
    captured = capsys.readouterr()
    assert '"total_sources": 1' in captured.out
    assert '"inventory_depth": "files"' in captured.out


def test_cli_estimate_sampled_tier(tmp_path, capsys):
    from unittest.mock import patch
    from videocompress.adapters.ffmpeg import SampleEncodeResult
    from videocompress.contracts import VideoAsset, VideoStream
    from videocompress.inventory import InventoryStore
    from videocompress.workspace import resolve_workspace

    media = tmp_path / "media"
    media.mkdir()
    v1 = media / "v1.mp4"
    v1.write_bytes(b"content" * 100)

    ws = resolve_workspace(media)
    store = InventoryStore(ws.inventory_db)

    vstream = VideoStream(stream_index=0, stream_type="video", codec_name="h264", width=1920, height=1080, bit_rate_bps=6_000_000)
    asset = VideoAsset(
        source_id="asset-cli-sample",
        relative_path="v1.mp4",
        file_bytes=100_000_000,
        container_format="mp4",
        duration_seconds=300.0,
        streams=(vstream,),
    )
    st = v1.stat()
    stat_fp = f"{st.st_mtime_ns}:{st.st_size}"
    store.save_asset(asset, canonical_path=str(v1), stat_fingerprint=stat_fp)

    mock_result = SampleEncodeResult(
        sample_path=tmp_path / "mock.mp4",
        source_path=v1,
        recipe_id="av1_nvenc_cq30",
        window_index=0,
        window_start=0.0,
        window_duration=10.0,
        actual_duration=10.0,
        sample_file_bytes=2_000_000,
        sample_video_bytes=1_998_000,
        sample_video_bps=1_598_400,
        encode_seconds=0.5,
        fps_throughput=480.0,
        encoder="av1_nvenc",
    )

    with patch("videocompress.adapters.ffmpeg.FFmpegAdapter.encode_sample_clip", return_value=mock_result):
        # 1. JSON output
        rc_json = main([
            "-N",
            "-J",
            "estimate",
            "-i",
            str(media),
            "-I",
            str(ws.root.parent),
            "--tier",
            "sampled",
            "-T",
            "3",
        ])
        assert rc_json == 0
        cap_json = capsys.readouterr()
        assert '"tier": "sampled"' in cap_json.out
        assert '"trials_recorded": 3' in cap_json.out
        assert '"measured_promising"' in cap_json.out

        # 2. Human-readable output
        rc_human = main([
            "-N",
            "estimate",
            "-i",
            str(media),
            "-I",
            str(ws.root.parent),
            "-E",
            "sampled",
            "-T",
            "3",
        ])
        assert rc_human == 0
        cap_human = capsys.readouterr()
        assert "Empirical Trial & Measurement Report (Tier 3 Sampled)" in cap_human.out
        assert "Trials Completed: 3" in cap_human.out


def test_compare_parser_arguments():
    parser = build_parser()
    args = parser.parse_args([
        "compare",
        "-i", "D:/Media",
        "-e", "av1_nvenc_cq30,hevc_nvenc_cq28",
        "-u", "s5",
        "-d", "15.0",
        "-q",
        "-P", "25.0",
        "-f",
    ])
    assert args.operation == "compare"
    assert args.input_target == "D:/Media"
    assert args.candidate_recipes == "av1_nvenc_cq30,hevc_nvenc_cq28"
    assert args.sample_schedule == "s5"
    assert args.sample_duration == 15.0
    assert args.skip_quality is True
    assert args.min_savings_pct == 25.0
    assert args.force_refresh is True


def test_preview_parser_arguments():
    parser = build_parser()
    args = parser.parse_args([
        "preview",
        "-i", "D:/Media",
        "-e", "av1_nvenc_cq34",
        "-n", "5",
        "-d", "8.0",
        "-m", "standalone",
    ])
    assert args.operation == "preview"
    assert args.input_target == "D:/Media"
    assert args.recipe_id == "av1_nvenc_cq34"
    assert args.num_clips == 5
    assert args.clip_duration == 8.0
    assert args.preview_mode == "standalone"


def test_cli_compare_dispatch(tmp_path, capsys):
    from unittest.mock import patch
    from videocompress.compare import AssetComparisonReport, RecipeComparisonResult
    from videocompress.contracts import VideoAsset, VideoStream
    from videocompress.inventory import InventoryStore
    from videocompress.workspace import resolve_workspace

    media = tmp_path / "media"
    media.mkdir()
    v1 = media / "v1.mp4"
    v1.write_bytes(b"content" * 100)

    ws = resolve_workspace(media)
    store = InventoryStore(ws.inventory_db)

    vstream = VideoStream(stream_index=0, stream_type="video", codec_name="h264", width=1920, height=1080, bit_rate_bps=6_000_000)
    asset = VideoAsset(
        source_id="asset-compare-test",
        relative_path="v1.mp4",
        file_bytes=100_000_000,
        container_format="mp4",
        duration_seconds=300.0,
        streams=(vstream,),
    )
    st = v1.stat()
    stat_fp = f"{st.st_mtime_ns}:{st.st_size}"
    store.save_asset(asset, canonical_path=str(v1), stat_fingerprint=stat_fp)

    mock_res1 = RecipeComparisonResult(
        recipe_id="av1_nvenc_cq30",
        encoder="av1_nvenc",
        codec="av1",
        cq=30.0,
        measured_mean_bps=2_000_000,
        predicted_container_bytes=40_000_000,
        predicted_savings_bytes=60_000_000,
        predicted_savings_pct=60.0,
        fps_throughput=400.0,
        encode_seconds=1.0,
        quality_ssim=0.9850,
        quality_psnr=42.5,
        quality_vmaf=None,
        is_pareto_efficient=True,
        rank=1,
    )
    mock_report = AssetComparisonReport(
        source_id="asset-compare-test",
        source_bytes=100_000_000,
        duration_seconds=300.0,
        recipe_results=[mock_res1],
        recommended_recipe_id="av1_nvenc_cq30",
    )

    with patch("videocompress.cli.run_recipe_comparison", return_value=mock_report):
        # 1. JSON
        rc_json = main([
            "-N",
            "-J",
            "compare",
            "-i", str(media),
            "-I", str(ws.root.parent),
            "-e", "av1_nvenc_cq30",
        ])
        assert rc_json == 0
        cap_json = capsys.readouterr()
        assert '"operation": "compare"' in cap_json.out
        assert '"av1_nvenc_cq30"' in cap_json.out
        assert '"is_pareto_efficient": true' in cap_json.out

        # 2. Human
        rc_human = main([
            "-N",
            "compare",
            "-i", str(media),
            "-I", str(ws.root.parent),
            "-e", "av1_nvenc_cq30",
        ])
        assert rc_human == 0
        cap_human = capsys.readouterr()
        assert "Recipe Comparison & Pareto Ranking" in cap_human.out
        assert "av1_nvenc_cq30" in cap_human.out
        assert "Pareto frontier computed" in cap_human.out


def test_cli_preview_dispatch(tmp_path, capsys):
    from unittest.mock import patch
    from videocompress.contracts import VideoAsset, VideoStream
    from videocompress.inventory import InventoryStore
    from videocompress.preview import PreviewClipRecord, PreviewManifest
    from videocompress.workspace import resolve_workspace

    media = tmp_path / "media"
    media.mkdir()
    v1 = media / "v1.mp4"
    v1.write_bytes(b"content" * 100)

    ws = resolve_workspace(media)
    store = InventoryStore(ws.inventory_db)

    vstream = VideoStream(stream_index=0, stream_type="video", codec_name="h264", width=1920, height=1080, bit_rate_bps=6_000_000)
    asset = VideoAsset(
        source_id="asset-prev-test",
        relative_path="v1.mp4",
        file_bytes=100_000_000,
        container_format="mp4",
        duration_seconds=300.0,
        streams=(vstream,),
    )
    st = v1.stat()
    stat_fp = f"{st.st_mtime_ns}:{st.st_size}"
    store.save_asset(asset, canonical_path=str(v1), stat_fingerprint=stat_fp)

    clip_rec = PreviewClipRecord(
        clip_id="prev_w0",
        source_id="asset-prev-test",
        recipe_id="av1_nvenc_cq30",
        window_index=0,
        start_seconds=10.0,
        duration_seconds=5.0,
        preview_mode="split",
        clip_path="workspace/previews/prev_w0.mp4",
        clip_bytes=1_000_000,
    )
    mock_manifest = PreviewManifest(
        manifest_id="manifest-test-001",
        target_path=str(v1),
        clips=[clip_rec],
    )

    with patch("videocompress.cli.generate_preview_clips", return_value=mock_manifest):
        # 1. JSON
        rc_json = main([
            "-N",
            "-J",
            "preview",
            "-i", str(media),
            "-I", str(ws.root.parent),
            "-n", "1",
        ])
        assert rc_json == 0
        cap_json = capsys.readouterr()
        assert '"operation": "preview"' in cap_json.out
        assert '"manifest_id": "manifest-test-001"' in cap_json.out

        # 2. Human
        rc_human = main([
            "-N",
            "preview",
            "-i", str(media),
            "-I", str(ws.root.parent),
            "-n", "1",
        ])
        assert rc_human == 0
        cap_human = capsys.readouterr()
        assert "Visual Preview Generator" in cap_human.out
        assert "manifest-test-001" in cap_human.out
        assert "Open preview clips in VLC" in cap_human.out

