from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from filter_prune import cli
from filter_prune.models import SafePruneError, TargetInfo
from filter_prune.operations import apply_targets, summarize_targets
from filter_prune.search import rg_file_matches_fd_context
from filter_prune.util import normalize_extension


def make_args(**overrides):
    defaults = {
        "execute": False,
        "yes": True,
        "operation": "delete",
        "target_dir": None,
        "recursive": False,
        "quiet": True,
        "verbose": False,
        "json": False,
        "color": "never",
        "script_command": None,
        "script_arg": [],
        "shell": False,
        "working_dir": None,
        "stop_on_error": False,
        "max_bytes": None,
        "encoding": "utf-8",
        "decode_errors": "replace",
        "allow_binary": False,
        "no_headers": False,
    }
    defaults.update(overrides)
    return Namespace(**defaults)


def make_target(path: Path, root: Path):
    return TargetInfo(path=path.resolve(strict=False), root=root.resolve(strict=False))


def test_apply_targets_dry_run_preserves_file_and_counts_would_be_affected(tmp_path):
    root = tmp_path
    target = root / "example-preview.mp4"
    target.write_text("hello", encoding="utf-8")

    args = make_args(execute=False)
    stats = apply_targets([make_target(target, root)], [root], args, "fd")

    assert target.exists()
    assert stats.dry_run is True
    assert stats.operation == "delete"
    assert stats.matched_count == 1
    assert stats.would_be_affected_count == 1
    assert stats.affected_count == 0
    assert stats.skipped_count == 0
    assert stats.failed_count == 0
    assert stats.summary.file_count == 1
    assert stats.summary.file_extension_counts == {".mp4": 1}
    assert stats.summary.total_file_size_bytes == 5


def test_apply_targets_execute_delete_file(tmp_path):
    root = tmp_path
    target = root / "example-preview.mp4"
    target.write_text("hello", encoding="utf-8")

    args = make_args(execute=True, operation="delete")
    stats = apply_targets([make_target(target, root)], [root], args, "fd")

    assert not target.exists()
    assert stats.dry_run is False
    assert stats.matched_count == 1
    assert stats.affected_count == 1
    assert stats.failed_count == 0


def test_apply_targets_execute_move_file(tmp_path):
    root = tmp_path / "root"
    target_dir = tmp_path / "moved"
    root.mkdir()
    target = root / "example-preview.mp4"
    target.write_text("hello", encoding="utf-8")

    args = make_args(execute=True, operation="move", target_dir=str(target_dir))
    stats = apply_targets([make_target(target, root)], [root], args, "fd")

    moved_files = list(target_dir.rglob("example-preview.mp4"))

    assert not target.exists()
    assert len(moved_files) == 1
    assert moved_files[0].read_text(encoding="utf-8") == "hello"
    assert stats.affected_count == 1
    assert stats.failed_count == 0


def test_apply_targets_execute_quarantine_file_with_default_target(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    target = root / "example-preview.mp4"
    target.write_text("hello", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    args = make_args(execute=True, operation="quarantine", target_dir=None)
    stats = apply_targets([make_target(target, root)], [root], args, "fd")

    moved_files = list((tmp_path / ".filter-prune-quarantine").rglob("example-preview.mp4"))

    assert not target.exists()
    assert len(moved_files) == 1
    assert moved_files[0].read_text(encoding="utf-8") == "hello"
    assert stats.affected_count == 1
    assert stats.failed_count == 0


def test_apply_targets_execute_script_operation(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    target = root / "example.txt"
    marker = tmp_path / "marker.txt"
    script = tmp_path / "script.py"

    target.write_text("hello", encoding="utf-8")
    script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "Path(sys.argv[1]).write_text(Path(sys.argv[2]).name, encoding='utf-8')\n",
        encoding="utf-8",
    )

    args = make_args(
        execute=True,
        operation="script",
        script_command=sys_executable(),
        script_arg=[str(script), str(marker), "{path}"],
    )
    stats = apply_targets([make_target(target, root)], [root], args, "fd")

    assert marker.read_text(encoding="utf-8") == "example.txt"
    assert target.exists()
    assert stats.affected_count == 1
    assert stats.failed_count == 0


def test_apply_targets_execute_cat_prints_file_contents_and_folder_names(tmp_path, capsys):
    root = tmp_path
    target = root / "example.txt"
    folder = root / "folder"
    target.write_text("hello\n", encoding="utf-8")
    folder.mkdir()

    args = make_args(execute=True, operation="cat", quiet=False)
    stats = apply_targets(
        [
            make_target(target, root),
            make_target(folder, root),
        ],
        [root],
        args,
        "fd",
    )

    captured = capsys.readouterr()

    assert "===== FILE:" in captured.out
    assert "hello" in captured.out
    assert "===== FOLDER:" in captured.out
    assert stats.affected_count == 2
    assert stats.failed_count == 0


def test_summarize_targets_counts_extensions_and_folder_size(tmp_path):
    root = tmp_path
    mp4_a = root / "a.mp4"
    mp4_b = root / "b.MP4"
    txt = root / "note.txt"
    folder = root / "folder"
    folder.mkdir()

    mp4_a.write_text("12345", encoding="utf-8")
    mp4_b.write_text("1234567", encoding="utf-8")
    txt.write_text("abc", encoding="utf-8")
    (folder / "child.bin").write_bytes(b"123456789")

    summary = summarize_targets([
        make_target(mp4_a, root),
        make_target(mp4_b, root),
        make_target(txt, root),
        make_target(folder, root),
    ])

    assert summary.file_count == 3
    assert summary.folder_count == 1
    assert summary.file_extension_counts == {
        ".mp4": 2,
        ".txt": 1,
    }
    assert summary.total_file_size_bytes == 15
    assert summary.total_folder_size_bytes == 9
    assert summary.total_size_bytes == 24


def test_normalize_extension_accepts_dot_prefix():
    assert normalize_extension(".mp4") == "mp4"


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
        cli.parse_cli(argv)

    assert exc_info.value.code == 0


def test_parse_cli_defaults_to_delete_dry_run_current_dir():
    parsed = cli.parse_cli([
        "fd",
        "-g",
        "*preview*",
    ])

    assert parsed.operation.operation == "delete"
    assert parsed.operation.execute is False
    assert parsed.operation.roots == []


def test_parse_cli_script_operation_args():
    parsed = cli.parse_cli([
        "-O",
        "script",
        "-S",
        "python",
        "-B",
        "script.py",
        "-B",
        "{path}",
        "fd",
        "-g",
        "*.txt",
    ])

    assert parsed.operation.operation == "script"
    assert parsed.operation.script_command == "python"
    assert parsed.operation.script_arg == ["script.py", "{path}"]


def test_parse_cli_cat_operation_args():
    parsed = cli.parse_cli([
        "-O",
        "cat",
        "-z",
        "100",
        "-u",
        "utf-8",
        "-d",
        "ignore",
        "fd",
        "-g",
        "*.txt",
    ])

    assert parsed.operation.operation == "cat"
    assert parsed.operation.max_bytes == 100
    assert parsed.operation.encoding == "utf-8"
    assert parsed.operation.decode_errors == "ignore"


def test_parse_cli_move_requires_target_dir_at_validation():
    parsed = cli.parse_cli([
        "-O",
        "move",
        "fd",
        "-g",
        "*preview*",
    ])

    with pytest.raises(SafePruneError):
        cli.validate_args(parsed)


def test_parse_cli_script_requires_script_command_at_validation():
    parsed = cli.parse_cli([
        "-O",
        "script",
        "fd",
        "-g",
        "*.txt",
    ])

    with pytest.raises(SafePruneError):
        cli.validate_args(parsed)


def test_parse_cli_multiple_roots_are_accumulated():
    parsed = cli.parse_cli([
        "-r",
        "B:\\stars",
        "fd",
        "-g",
        "*preview*",
        "-r",
        "D:\\tmp",
    ])

    assert parsed.operation.roots == ["B:\\stars", "D:\\tmp"]


def test_parse_cli_fd_rg_keeps_separate_args():
    parsed = cli.parse_cli([
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
    parsed = cli.parse_cli([
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
    parsed = cli.parse_cli([
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
    parsed = cli.parse_cli([
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

    inside_target = make_target(inside, tmp_path)
    outside_target = make_target(outside, tmp_path)
    folder_target = make_target(folder, tmp_path)

    assert rg_file_matches_fd_context(inside_target, [folder_target]) is True
    assert rg_file_matches_fd_context(outside_target, [folder_target]) is False


def sys_executable() -> str:
    import sys

    return sys.executable
