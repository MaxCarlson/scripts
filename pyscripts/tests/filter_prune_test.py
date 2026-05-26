from __future__ import annotations

import importlib.util
import sys
from argparse import Namespace
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "filter-prune.py"
SPEC = importlib.util.spec_from_file_location("filter_prune", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None

filter_prune = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = filter_prune
SPEC.loader.exec_module(filter_prune)


def make_args(**overrides):
    defaults = {
        "delete": False,
        "yes": True,
        "quarantine_dir": None,
        "recursive": False,
        "quiet": True,
        "verbose": False,
        "json": False,
        "color": "never",
    }
    defaults.update(overrides)
    return Namespace(**defaults)


def test_apply_targets_dry_run_preserves_file_and_counts_would_be_affected(tmp_path):
    root = tmp_path
    target = root / "example-preview.mp4"
    target.write_text("hello", encoding="utf-8")

    args = make_args(delete=False)
    stats = filter_prune.apply_targets([target], root, args, "fd")

    assert target.exists()
    assert stats.dry_run is True
    assert stats.matched_count == 1
    assert stats.would_be_affected_count == 1
    assert stats.affected_count == 0
    assert stats.skipped_count == 0
    assert stats.failed_count == 0


def test_print_stats_dry_run_uses_would_be_affected_summary(tmp_path, capsys):
    root = tmp_path
    target = root / "example-preview.mp4"
    target.write_text("hello", encoding="utf-8")

    args = make_args(delete=False, quiet=False, color="never")
    stats = filter_prune.apply_targets([target], root, args, "fd")
    filter_prune.print_stats_text(stats, args)
    captured = capsys.readouterr()

    assert "DRY-RUN:" in captured.out
    assert "would affect" not in captured.out
    assert "Would be affected: 1" in captured.out
    assert "Affected: 0" not in captured.out
    assert "Skipped: 0" in captured.out


def test_apply_targets_delete_file(tmp_path):
    root = tmp_path
    target = root / "example-preview.mp4"
    target.write_text("hello", encoding="utf-8")

    args = make_args(delete=True)
    stats = filter_prune.apply_targets([target], root, args, "fd")

    assert not target.exists()
    assert stats.dry_run is False
    assert stats.matched_count == 1
    assert stats.would_be_affected_count == 0
    assert stats.affected_count == 1
    assert stats.failed_count == 0


def test_apply_targets_non_empty_directory_without_recursive_fails(tmp_path):
    root = tmp_path
    target = root / "preview-folder"
    target.mkdir()
    (target / "child.txt").write_text("hello", encoding="utf-8")

    args = make_args(delete=True, recursive=False)
    stats = filter_prune.apply_targets([target], root, args, "fd")

    assert target.exists()
    assert stats.affected_count == 0
    assert stats.failed_count == 1


def test_apply_targets_non_empty_directory_with_recursive_deletes(tmp_path):
    root = tmp_path
    target = root / "preview-folder"
    target.mkdir()
    (target / "child.txt").write_text("hello", encoding="utf-8")

    args = make_args(delete=True, recursive=True)
    stats = filter_prune.apply_targets([target], root, args, "fd")

    assert not target.exists()
    assert stats.affected_count == 1
    assert stats.failed_count == 0


def test_apply_targets_quarantine_moves_file(tmp_path):
    root = tmp_path / "root"
    quarantine = tmp_path / "quarantine"
    root.mkdir()
    target = root / "example-preview.mp4"
    target.write_text("hello", encoding="utf-8")

    args = make_args(delete=True, quarantine_dir=str(quarantine))
    stats = filter_prune.apply_targets([target], root, args, "fd")

    moved_files = list(quarantine.rglob("example-preview.mp4"))

    assert not target.exists()
    assert len(moved_files) == 1
    assert moved_files[0].read_text(encoding="utf-8") == "hello"
    assert stats.affected_count == 1
    assert stats.failed_count == 0


def test_normalize_extension_accepts_dot_prefix():
    assert filter_prune.normalize_extension(".mp4") == "mp4"


@pytest.mark.parametrize(
    "argv",
    [
        ["--help"],
        ["fd", "--help"],
        ["rg", "--help"],
        ["fd", "rg", "--help"],
        ["rg", "fd", "-?"],
    ],
)
def test_help_menus_exit_success(argv):
    with pytest.raises(SystemExit) as exc_info:
        filter_prune.parse_cli(argv)

    assert exc_info.value.code == 0


def test_parse_cli_fd_rg_keeps_separate_args():
    parsed = filter_prune.parse_cli([
        "fd",
        "-g",
        "*preview*",
        "-e",
        "mp4",
        "rg",
        "-p",
        "needle",
        "-g",
        "*.txt",
    ])

    assert parsed.order == ("fd", "rg")
    assert parsed.fd.glob_pattern == ["*preview*"]
    assert parsed.fd.extension == ["mp4"]
    assert parsed.rg.content_pattern == ["needle"]
    assert parsed.rg.glob_pattern == ["*.txt"]


def test_parse_cli_rg_fd_order_is_preserved():
    parsed = filter_prune.parse_cli([
        "rg",
        "-p",
        "needle",
        "fd",
        "-g",
        "*preview*",
    ])

    assert parsed.order == ("rg", "fd")
    assert parsed.rg.content_pattern == ["needle"]
    assert parsed.fd.glob_pattern == ["*preview*"]


def test_parse_cli_no_ignore_defaults_to_true_for_fd_and_rg():
    parsed = filter_prune.parse_cli([
        "fd",
        "-g",
        "*preview*",
        "rg",
        "-p",
        "needle",
    ])

    assert parsed.fd.no_ignore is True
    assert parsed.rg.no_ignore is True


def test_parse_cli_respect_ignore_disables_no_ignore():
    parsed = filter_prune.parse_cli([
        "fd",
        "-G",
        "-g",
        "*preview*",
        "rg",
        "-G",
        "-p",
        "needle",
    ])

    assert parsed.fd.no_ignore is False
    assert parsed.rg.no_ignore is False


def test_rg_file_matches_fd_folder_context(tmp_path):
    folder = tmp_path / "matched-folder"
    folder.mkdir()
    inside = folder / "inside.txt"
    outside = tmp_path / "outside.txt"
    inside.write_text("needle", encoding="utf-8")
    outside.write_text("needle", encoding="utf-8")

    assert filter_prune.rg_file_matches_fd_context(inside, [folder]) is True
    assert filter_prune.rg_file_matches_fd_context(outside, [folder]) is False
