from __future__ import annotations

from pathlib import Path

from file_utils import cli, file_growth_monitor


def test_scan_directory_counts_nested_files_and_root_files(tmp_path: Path) -> None:
    (tmp_path / "root.txt").write_bytes(b"root")
    child = tmp_path / "child"
    child.mkdir()
    (child / "nested.bin").write_bytes(b"nested")

    without_root = file_growth_monitor.scan_directory(tmp_path)
    with_root = file_growth_monitor.scan_directory(tmp_path, include_root_files=True)

    assert without_root.folders == 1
    assert without_root.files == 1
    assert without_root.size == 6
    assert with_root.files == 2
    assert with_root.size == 10


def test_monitor_argument_validation_and_interval_normalization() -> None:
    args = file_growth_monitor.parse_args(["-s", "5", "-p", "2", "-n", "1", "-X"])

    assert args.scan_interval == 2
    assert args.print_interval == 2
    assert args.max_scans == 1
    assert args.no_interactive


def test_file_utils_cli_monitor_runs_one_noninteractive_scan(tmp_path: Path) -> None:
    (tmp_path / "sample.txt").write_text("sample", encoding="utf-8")

    result = cli.main([
        "monitor",
        "--path",
        str(tmp_path),
        "--max-scans",
        "1",
        "--no-interactive",
        "--no-color",
    ])

    assert result == 0
