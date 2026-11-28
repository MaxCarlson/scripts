from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from clipboard_tools import compare_cli, entrypoints


@pytest.fixture
def cli():
    return compare_cli


def test_compare_files_uses_existing_normalized_and_strict_semantics(tmp_path: Path, cli):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_bytes(b"alpha\r\n")
    second.write_bytes(b"alpha\n")

    assert cli.compare_files(first, second).equal is True
    assert cli.compare_files(first, second, strict=True).equal is False


def test_compare_files_reports_encoding_and_read_errors(tmp_path: Path, cli):
    valid = tmp_path / "valid.txt"
    binary = tmp_path / "binary.txt"
    valid.write_text("ok", encoding="utf-8")
    binary.write_bytes(b"\xff")

    assert "Encoding error" in cli.compare_files(valid, binary).error
    assert "Could not read file" in cli.compare_files(valid, tmp_path / "missing.txt").error


def test_cld_reports_identical_or_larger_side_in_characters(tmp_path: Path, monkeypatch, capsys, cli):
    target = tmp_path / "target.txt"
    target.write_text("small", encoding="utf-8")
    monkeypatch.setattr(cli, "get_clipboard", lambda: "larger text")

    assert cli.clipboard_summary_main([str(target)]) == 0
    output = capsys.readouterr().out
    assert "clipboard is larger by 6 characters" in output

    target.write_text("larger text", encoding="utf-8")
    assert cli.clipboard_summary_main([str(target)]) == 0
    assert "Identical (normalized)" in capsys.readouterr().out

    target.write_text("larger text!", encoding="utf-8")
    assert cli.clipboard_summary_main([str(target)]) == 0
    assert "target file is larger by 1 character" in capsys.readouterr().out


def test_comp_compares_every_unordered_file_pair(tmp_path: Path, capfd, cli):
    files = [tmp_path / name for name in ("one.txt", "two.txt", "three.txt")]
    for index, path in enumerate(files):
        path.write_text("x" * (index + 1), encoding="utf-8")

    assert cli.compare_files_main([*(str(path) for path in files)]) == 1
    output = capfd.readouterr().out
    assert "one.txt" in output and "two.txt" in output and "three.txt" in output
    assert output.count(": Different -") == 3


def test_compd_places_all_details_before_final_summary(tmp_path: Path, capfd, cli):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    third = tmp_path / "third.txt"
    first.write_text("alpha\n", encoding="utf-8")
    second.write_text("beta\n", encoding="utf-8")
    third.write_text("gamma\n", encoding="utf-8")

    assert cli.compare_files_main([str(first), str(second), str(third)], detailed=True) == 1
    output = capfd.readouterr().out
    assert output.count("--- ") == 3
    assert output.count("+++ ") == 3
    assert output.rfind("Summary") > output.rfind("--- ")


def test_comp_fd_expands_nul_delimited_results_to_paths(tmp_path: Path, monkeypatch, capfd, cli):
    files = [tmp_path / "one,part.txt", tmp_path / "two file.txt"]
    for index, path in enumerate(files):
        path.write_text("x" * (index + 1), encoding="utf-8")

    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return CompletedProcess(command, 0, stdout=(str(files[0]) + "\0" + str(files[1]) + "\0").encode(), stderr=b"")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    assert cli.compare_files_main(["fd", "AGENTS.md"]) == 1
    assert calls == [["fd", "--print0", "AGENTS.md"]]
    output = capfd.readouterr().out
    assert "one,part.txt" in output and "two file.txt" in output


def test_comp_fd_reports_no_matches(tmp_path: Path, monkeypatch, capfd, cli):
    def fake_run(command, **kwargs):
        return CompletedProcess(command, 1, stdout=b"", stderr=b"")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    assert cli.compare_files_main(["fd", "missing.md"]) == 2
    assert "no files" in capfd.readouterr().err.lower()


def test_console_scripts_keep_legacy_diff_and_register_new_commands():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    scripts = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["scripts"]

    assert scripts["cld"] == "clipboard_tools.entrypoints:clipboard_summary_main"
    assert scripts["cldd"] == "clipboard_tools.entrypoints:clipboard_diff_main"
    assert scripts["comp"] == "clipboard_tools.entrypoints:compare_files_main"
    assert scripts["compd"] == "clipboard_tools.entrypoints:compare_files_detailed_main"


def test_repo_launcher_manifest_discovers_comparison_commands():
    from scripts_setup.launcher_generator import scan_repository_programs

    repo_root = Path(__file__).resolve().parents[3]
    commands = scan_repository_programs(repo_root)

    assert commands["comp"].distribution == "clipboard_tools"
    assert commands["compd"].distribution == "clipboard_tools"
    assert commands["cldd"].entry_point == "clipboard_tools.entrypoints:clipboard_diff_main"


@pytest.mark.parametrize(
    ("argv", "entrypoint", "implementation", "forwarded"),
    [
        (["comp", "one.txt", "two.txt"], entrypoints.compare_files_main, "compare_main", ["one.txt", "two.txt"]),
        (
            ["compd", "one.txt", "two.txt"],
            entrypoints.compare_files_detailed_main,
            "compare_detailed_main",
            ["one.txt", "two.txt"],
        ),
        (["cld", "one.txt"], entrypoints.clipboard_summary_main, "clipboard_summary_main", ["one.txt"]),
    ],
)
def test_new_entrypoints_forward_arguments(monkeypatch, argv, entrypoint, implementation, forwarded):
    monkeypatch.setattr(sys, "argv", argv)
    with patch(f"clipboard_tools.compare_cli.{implementation}", return_value=0) as main:
        with pytest.raises(SystemExit) as exc:
            entrypoint()
    assert exc.value.code == 0
    main.assert_called_once_with(forwarded)
