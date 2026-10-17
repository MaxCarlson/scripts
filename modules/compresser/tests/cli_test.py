from __future__ import annotations

from pathlib import Path

import pytest

from compresser.arguments import normalize_compression_arguments
from compresser.cli import build_parser, main as _main
from cli_test_support import main


def test_cli_parser_builds_operation_and_typed_apply_options():
    parsed = build_parser().parse_args(["apply", "-i", "foo", "-f", "webp", "-m", "lossy", "-q", "0.85", "-w", "-L"])
    options = normalize_compression_arguments(parsed)
    assert options.operation == "apply"
    assert options.target == Path("foo")
    assert options.recipes[0].quality == 85
    assert options.write and options.allow_lossy


def test_bare_cli_prints_operation_help_without_scanning(capsys):
    assert main([]) == 0
    assert "inventory" in capsys.readouterr().out


def test_removed_flat_flag_fails_before_creating_workspace(sample_images_dir: Path, capsys):
    with pytest.raises(SystemExit):
        _main(["-i", str(sample_images_dir), "-l"])
    assert not (sample_images_dir.parent / ".compresser").exists()
    error = capsys.readouterr().err
    assert "invalid choice" in error or "unrecognized arguments" in error


def test_cli_dry_run_execution(sample_images_dir: Path, capsys):
    ret = main(["analyze", "-i", str(sample_images_dir), "-f", "webp", "-m", "perceptual", "-N"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "COMPRESSION ANALYSIS" in captured.out and "Read-only" in captured.out


def test_cli_compare_execution(sample_images_dir: Path, capsys):
    ret = main(["compare", "-i", str(sample_images_dir), "-f", "webp", "-m", "lossy", "-q", "85", "-N"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "Comparison Matrix" in captured.out or "Strategy" in captured.out


def test_cli_plan_and_estimate_execution(sample_images_dir: Path, capsys):
    import json

    base = ["-i", str(sample_images_dir), "-I", str(sample_images_dir.parent), "-N", "-J"]
    # 1. Inventory
    assert main(["inventory", *base]) == 0
    capsys.readouterr()

    # 2. Plan
    assert main(["plan", *base, "-f", "webp", "-m", "lossy", "-q", "80"]) == 0
    plan_out = json.loads(capsys.readouterr().out)
    plan_id = plan_out["plan"]["plan_id"]

    # 3. Estimate with -r
    assert main(["estimate", *base, "-r", plan_id]) == 0
    est_out = json.loads(capsys.readouterr().out)
    assert est_out["operation"] == "estimate"
    assert est_out["stopping_reason"] == "complete"
    assert est_out["new_encodes"] > 0
    assert len(est_out["estimates"]) == 1

    # 4. Estimate without -J (renders summary)
    non_json_base = ["-i", str(sample_images_dir), "-I", str(sample_images_dir.parent), "-N"]
    assert main(["estimate", *non_json_base, "-r", plan_id]) == 0
    rendered = capsys.readouterr().out
    assert "Compression estimate" in rendered
    assert "WebP" in rendered


def test_cli_estimate_incompatible_rejection(sample_images_dir: Path, capsys):
    import json

    base = ["-i", str(sample_images_dir), "-I", str(sample_images_dir.parent), "-N", "-J"]
    # 1. Inventory & plan
    assert main(["inventory", *base]) == 0
    capsys.readouterr()
    assert main(["plan", *base, "-f", "webp", "-m", "lossy", "-q", "80", "-z", "42"]) == 0
    plan_out = json.loads(capsys.readouterr().out)
    plan_id = plan_out["plan"]["plan_id"]

    # 2. Conflicting recipe rejection
    ret = main(
        [
            "estimate",
            "-i",
            str(sample_images_dir),
            "-I",
            str(sample_images_dir.parent),
            "-r",
            plan_id,
            "-f",
            "jpeg",
            "-m",
            "lossy",
            "-q",
            "80",
            "-N",
        ]
    )
    assert ret == 2
    err = capsys.readouterr().err
    assert "differs from the saved plan" in err

    # 3. Conflicting seed rejection
    ret_seed = main(
        [
            "estimate",
            "-i",
            str(sample_images_dir),
            "-I",
            str(sample_images_dir.parent),
            "-r",
            plan_id,
            "-z",
            "999",
            "-N",
        ]
    )
    assert ret_seed == 2
    err_seed = capsys.readouterr().err
    assert "seed differs from the saved plan" in err_seed


def test_cli_estimate_without_plan_flag_creates_and_runs(sample_images_dir: Path, capsys):
    import json

    base = ["-i", str(sample_images_dir), "-I", str(sample_images_dir.parent), "-N", "-J"]
    # 1. Inventory
    assert main(["inventory", *base]) == 0
    capsys.readouterr()

    # 2. Estimate directly without -r
    ret = main(["estimate", *base, "-f", "webp", "-m", "lossy", "-q", "80"])
    assert ret == 0
    out = json.loads(capsys.readouterr().out)
    assert out["operation"] == "estimate"
    assert out["stopping_reason"] == "complete"
    assert out["new_encodes"] > 0
    assert len(out["estimates"]) == 1
