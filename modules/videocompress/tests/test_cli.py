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
