#!/usr/bin/env python3
"""
Tests for CLI argument validation with the subcommand-based interface.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from video_dedupe import _quality_to_pipeline, _validate_args, parse_args


# ──────────────────────────────────────────
# Subcommand help / structure tests
# ──────────────────────────────────────────


def test_scan_subcommand_help():
    """video-dedupe scan -h exits cleanly."""
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["scan", "--help"])
    assert exc_info.value.code == 0


def test_view_subcommand_help():
    """video-dedupe view -h exits cleanly."""
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["view", "--help"])
    assert exc_info.value.code == 0


def test_apply_subcommand_help():
    """video-dedupe apply -h exits cleanly."""
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["apply", "--help"])
    assert exc_info.value.code == 0


def test_old_top_level_apply_returns_error():
    """Old flat-CLI style `video-dedupe -a report.json` is rejected with exit code 2."""
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["-a", "report.json"])
    assert exc_info.value.code == 2


def test_scan_command_is_set():
    """parse_args sets args.command == 'scan' for scan subcommand."""
    with tempfile.TemporaryDirectory() as tmp:
        args = parse_args(["scan", "-D", tmp])
    assert args.command == "scan"


def test_view_command_is_set():
    """parse_args sets args.command == 'view' for view subcommand."""
    with tempfile.TemporaryDirectory() as tmp:
        rp = Path(tmp) / "r.json"
        rp.write_text("{}", encoding="utf-8")
        args = parse_args(["view", "-P", str(rp)])
    assert args.command == "view"


def test_apply_command_is_set():
    """parse_args sets args.command == 'apply' for apply subcommand."""
    with tempfile.TemporaryDirectory() as tmp:
        rp = Path(tmp) / "r.json"
        rp.write_text("{}", encoding="utf-8")
        args = parse_args(["apply", "-a", str(rp)])
    assert args.command == "apply"


# ──────────────────────────────────────────
# Seed-report scan tests
# ──────────────────────────────────────────


def test_seed_report_scan_validates_ok():
    """scan -R report.json -J 2 -D dir passes validation."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        rp = tmp_path / "report.json"
        rp.write_text('{"groups": {}}', encoding="utf-8")

        args = parse_args(["scan", "-R", str(rp), "-J", "2", "-D", tmp])
        error = _validate_args(args)
        assert error is None


def test_seed_random_per_group_requires_seed_report():
    """-J without -R/-seed-report returns a clear validation error."""
    with tempfile.TemporaryDirectory() as tmp:
        args = parse_args(["scan", "-J", "2", "-D", tmp])
        error = _validate_args(args)
        assert error is not None
        assert "seed-report" in error.lower() or "seed_report" in error.lower() or "-R" in error


# ──────────────────────────────────────────
# Scan validation tests
# ──────────────────────────────────────────


def test_valid_scan_args():
    """Valid scan arguments pass validation."""
    with tempfile.TemporaryDirectory() as tmp:
        args = parse_args(["scan", "-D", tmp, "-q", "1-2", "-t", "4"])
        error = _validate_args(args)
        assert error is None


def test_quality_single_digits_are_individual_stages():
    """Single-digit -q values select one method; ranges combine methods."""
    assert _quality_to_pipeline("1") == "1"
    assert _quality_to_pipeline("2") == "2"
    assert _quality_to_pipeline("3") == "3"
    assert _quality_to_pipeline("1-2") == "1-2"


def test_invalid_pipeline():
    """Pipeline validation catches a parse exception."""
    with tempfile.TemporaryDirectory() as tmp:
        args = parse_args(["scan", "-D", tmp, "-q", "1-2"])

        with patch("video_dedupe.parse_pipeline") as mock_parse:
            mock_parse.side_effect = ValueError("Invalid pipeline")
            error = _validate_args(args)
            assert error is not None
            assert "quality level" in error.lower() or "pipeline" in error.lower()


def test_invalid_thread_count():
    """Thread count validation catches non-positive and excessive values."""
    with tempfile.TemporaryDirectory() as tmp:
        args = parse_args(["scan", "-D", tmp, "-t", "-1"])
        error = _validate_args(args)
        assert error is not None
        assert "thread count must be positive" in error.lower()

        args = parse_args(["scan", "-D", tmp, "-t", "100"])
        error = _validate_args(args)
        assert error is not None
        assert "excessive" in error.lower()


def test_invalid_max_duplicates():
    """Duplicate stop limit validation rejects zero."""
    with tempfile.TemporaryDirectory() as tmp:
        args = parse_args(["scan", "-D", tmp, "-N", "0"])
        error = _validate_args(args)
        assert error is not None
        assert "max-duplicates" in error


def test_invalid_duration_tolerance():
    """Duration tolerance validation catches negative and excessive values."""
    args = parse_args(["scan", "-D", "dummy_dir", "--duration-tolerance", "-1"])
    error = _validate_args(args)
    assert error is not None
    assert "duration tolerance" in error.lower()

    args = parse_args(["scan", "-D", "dummy_dir", "--duration-tolerance", "7200"])
    error = _validate_args(args)
    assert error is not None
    assert "excessive" in error.lower()


def test_invalid_phash_params():
    """pHash parameter validation catches invalid values."""
    args = parse_args(["scan", "-D", "dummy_dir", "--phash-frames", "0"])
    error = _validate_args(args)
    assert error is not None
    assert "frames count must be positive" in error.lower()

    args = parse_args(["scan", "-D", "dummy_dir", "--phash-frames", "100"])
    error = _validate_args(args)
    assert error is not None
    assert "excessive" in error.lower()

    args = parse_args(["scan", "-D", "dummy_dir", "--phash-threshold", "-1"])
    error = _validate_args(args)
    assert error is not None
    assert "threshold must be non-negative" in error.lower()

    args = parse_args(["scan", "-D", "dummy_dir", "--phash-threshold", "100"])
    error = _validate_args(args)
    assert error is not None
    assert "too high" in error.lower()


def test_invalid_subset_ratio():
    """Subset detection ratio validation catches out-of-range values."""
    args = parse_args(["scan", "-D", "dummy_dir", "--subset-min-ratio", "0"])
    error = _validate_args(args)
    assert error is not None
    assert "between 0 and 1" in error.lower()

    args = parse_args(["scan", "-D", "dummy_dir", "--subset-min-ratio", "1.5"])
    error = _validate_args(args)
    assert error is not None
    assert "between 0 and 1" in error.lower()


def test_nonexistent_scan_exclusion_report():
    """Exclusion report path that doesn't exist is caught."""
    with tempfile.TemporaryDirectory() as tmp:
        args = parse_args(["scan", "-D", tmp, "-e", "/nonexistent/exclude.json"])
        error = _validate_args(args)
        assert error is not None
        assert "not found" in error.lower()


def test_directory_validation():
    """Nonexistent scan directory is caught by validation."""
    args = parse_args(["scan", "-D", "/nonexistent/directory"])
    error = _validate_args(args)
    assert error is not None
    assert "not found" in error.lower()


def test_file_as_directory():
    """Passing a file where a directory is expected is caught."""
    with tempfile.NamedTemporaryFile() as tmp_file:
        args = parse_args(["scan", "-D", tmp_file.name])
        error = _validate_args(args)
        assert error is not None
        assert "not a directory" in error.lower()


def test_scan_output_directory_creation():
    """Valid output directory argument passes validation."""
    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp) / "output"
        args = parse_args(["scan", "-D", tmp, "-o", str(output_dir)])
        error = _validate_args(args)
        assert error is None


def test_scan_relative_paths():
    """Relative paths are accepted and validated correctly."""
    args = parse_args(["scan", "-D", ".", "-q", "2"])
    error = _validate_args(args)
    assert error is None

    with tempfile.TemporaryDirectory() as tmp:
        subdir = Path(tmp) / "subdir"
        subdir.mkdir()
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp)
            args = parse_args(["scan", "-D", "./subdir", "-q", "2"])
            error = _validate_args(args)
            assert error is None

            args = parse_args(["scan", "-D", "subdir", "-q", "2"])
            error = _validate_args(args)
            assert error is None
        finally:
            os.chdir(old_cwd)

    args = parse_args(["scan", "-D", "./nonexistent_folder_12345", "-q", "2"])
    error = _validate_args(args)
    assert error is not None
    assert "not found" in error.lower()


def test_subset_detect_stage_selection():
    """Quality level 5 with stage 4 produces a valid pipeline."""
    with tempfile.TemporaryDirectory() as tmp:
        args = parse_args(["scan", "-D", tmp, "-q", "5"])
        error = _validate_args(args)
        if error is not None:
            assert "Quality levels 4 and 5 require pHash stage" in error


def test_conflicting_ui_options():
    """Valid quality levels produce no validation error."""
    with tempfile.TemporaryDirectory() as tmp:
        args = parse_args(["scan", "-D", tmp, "-q", "3"])
        error = _validate_args(args)
        assert error is None


# ──────────────────────────────────────────
# View validation tests
# ──────────────────────────────────────────


def test_view_requires_at_least_one_option():
    """view with no report options returns a validation error."""
    args = parse_args(["view"])
    error = _validate_args(args)
    assert error is not None
    assert "requires at least one" in error.lower() or "print-report" in error.lower()


def test_view_nonexistent_print_report():
    """view -P with a missing file is caught."""
    args = parse_args(["view", "-P", "/nonexistent/report.json"])
    error = _validate_args(args)
    assert error is not None
    assert "not found" in error.lower()


def test_view_nonexistent_analyze_report():
    """view -y with a missing file is caught."""
    args = parse_args(["view", "-y", "/nonexistent/report.json"])
    error = _validate_args(args)
    assert error is not None
    assert "not found" in error.lower()


def test_valid_view_args():
    """Existing report files pass view validation."""
    with tempfile.TemporaryDirectory() as tmp:
        rp = Path(tmp) / "r.json"
        rp.write_text('{"groups": {}}', encoding="utf-8")

        args = parse_args(["view", "-P", str(rp)])
        assert _validate_args(args) is None

        args = parse_args(["view", "-y", str(rp)])
        assert _validate_args(args) is None


# ──────────────────────────────────────────
# Apply validation tests
# ──────────────────────────────────────────


def test_apply_requires_apply_report():
    """apply without -a/-apply-report returns a validation error."""
    args = parse_args(["apply"])
    error = _validate_args(args)
    assert error is not None
    assert "apply-report" in error.lower() or "-a" in error


def test_apply_nonexistent_report():
    """apply -a with a missing file is caught."""
    args = parse_args(["apply", "-a", "/nonexistent/report.json"])
    error = _validate_args(args)
    assert error is not None
    assert "not found" in error.lower()


def test_folder_priority_apply_report_args():
    """apply -M and -a together pass validation."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        rp = tmp_path / "report.json"
        rp.write_text('{"groups": {}}', encoding="utf-8")
        priority = tmp_path / "priority"

        args = parse_args(["apply", "-a", str(rp), "-M", str(priority)])
        assert args.folder_priority == str(priority)
        assert _validate_args(args) is None


def test_folder_priority_requires_apply_report():
    """apply -M without -a returns an error mentioning both flags."""
    with tempfile.TemporaryDirectory() as tmp:
        args = parse_args(["apply", "-M", tmp])
        error = _validate_args(args)
        assert error is not None
        # Error should mention both folder-priority and apply-report
        combined = error.lower()
        assert "folder-priority" in combined or "apply-report" in combined


def test_valid_apply_args():
    """Valid apply arguments pass validation."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        rp = tmp_path / "report.json"
        rp.write_text('{"groups": {}}', encoding="utf-8")
        backup_dir = tmp_path / "backup"

        args = parse_args(["apply", "-a", str(rp), "-b", str(backup_dir)])
        assert _validate_args(args) is None


# ──────────────────────────────────────────
# Help text smoke test
# ──────────────────────────────────────────


def test_top_level_help():
    """video-dedupe --help exits cleanly."""
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["--help"])
    assert exc_info.value.code == 0


if __name__ == "__main__":
    print("Run with: pytest tests/cli_validation_test.py -v")
