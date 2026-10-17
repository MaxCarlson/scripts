from __future__ import annotations

from pathlib import Path
from compresser.cli import build_parser, main


def test_cli_parser_options():
    parser = build_parser()
    args = parser.parse_args(["-i", "foo", "-f", "webp", "-m", "lossy", "-q", "85", "-w"])
    assert args.input == Path("foo")
    assert args.format == "webp"
    assert args.mode == "lossy"
    assert args.quality == 85
    assert args.write is True


def test_cli_dry_run_execution(sample_images_dir: Path, capsys):
    ret = main(["-i", str(sample_images_dir), "-f", "webp", "-m", "perceptual", "-N"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "COMPRESSION ANALYSIS" in captured.out and "Read-only" in captured.out


def test_cli_compare_execution(sample_images_dir: Path, capsys):
    ret = main(["-i", str(sample_images_dir), "-c", "-N"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "Comparison Matrix" in captured.out or "Strategy" in captured.out
