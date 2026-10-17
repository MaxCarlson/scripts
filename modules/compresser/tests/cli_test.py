from __future__ import annotations

from pathlib import Path

import pytest

from compresser.arguments import normalize_compression_arguments
from compresser.cli import build_parser, main as _main
from cli_test_support import main


def test_cli_parser_builds_operation_and_typed_apply_options():
    parsed = build_parser().parse_args(
        ["apply", "-i", "foo", "-f", "webp", "-m", "lossy", "-q", "0.85", "-w", "-L"]
    )
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
