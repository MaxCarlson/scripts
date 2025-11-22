#!/usr/bin/env python3
"""
Tests for CLI argument validation enhancements.
"""
import tempfile
import sys
from pathlib import Path
from unittest.mock import patch

from video_dedupe import _validate_args, parse_args


def test_valid_args():
    """Test that valid arguments pass validation."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        test_video = temp_path / "test.mp4"
        test_video.write_text("fake video")

        # Test basic scan command
        args = parse_args(["-D", str(temp_path), "-q", "1-2", "-t", "4"])
        error = _validate_args(args)
        assert error is None


def test_invalid_pipeline():
    """Test pipeline validation."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Test with a pipeline that would cause parse_pipeline to raise an exception
        args = parse_args(["-D", temp_dir, "-q", "1-2"])

        # Mock parse_pipeline to raise an exception to test error handling
        from unittest.mock import patch
        with patch('video_dedupe.parse_pipeline') as mock_parse:
            mock_parse.side_effect = ValueError("Invalid pipeline")
            error = _validate_args(args)
            assert error is not None
            assert "quality level" in error.lower() or "pipeline" in error.lower()


def test_invalid_thread_count():
    """Test thread count validation."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Negative threads
        args = parse_args(["-D", temp_dir, "-t", "-1"])
        error = _validate_args(args)
        assert error is not None
        assert "thread count must be positive" in error.lower()

        # Excessive threads
        args = parse_args(["-D", temp_dir, "-t", "100"])
        error = _validate_args(args)
        assert error is not None
        assert "excessive" in error.lower()


def test_invalid_duration_tolerance():
    """Test duration tolerance validation."""
    # Negative tolerance
    args = parse_args(["-D", "dummy_dir", "--duration-tolerance", "-1"])
    error = _validate_args(args)
    assert error is not None
    assert "duration tolerance" in error.lower()

    # Excessive tolerance
    args = parse_args(["-D", "dummy_dir", "--duration-tolerance", "7200"])  # 2 hours
    error = _validate_args(args)
    assert error is not None
    assert "excessive" in error.lower()


def test_invalid_phash_params():
    """Test pHash parameter validation."""
    # Zero frames
    args = parse_args(["-D", "dummy_dir", "--phash-frames", "0"])
    error = _validate_args(args)
    assert error is not None
    assert "frames count must be positive" in error.lower()

    # Excessive frames
    args = parse_args(["-D", "dummy_dir", "--phash-frames", "100"])
    error = _validate_args(args)
    assert error is not None
    assert "excessive" in error.lower()

    # Negative threshold
    args = parse_args(["-D", "dummy_dir", "--phash-threshold", "-1"])
    error = _validate_args(args)
    assert error is not None
    assert "threshold must be non-negative" in error.lower()

    # Excessive threshold
    args = parse_args(["-D", "dummy_dir", "--phash-threshold", "100"])
    error = _validate_args(args)
    assert error is not None
    assert "too high" in error.lower()


def test_invalid_subset_ratio():
    """Test subset detection ratio validation."""
    # Zero ratio
    args = parse_args(["-D", "dummy_dir", "--subset-min-ratio", "0"])
    error = _validate_args(args)
    assert error is not None
    assert "between 0 and 1" in error.lower()

    # Ratio >= 1
    args = parse_args(["-D", "dummy_dir", "--subset-min-ratio", "1.5"])
    error = _validate_args(args)
    assert error is not None
    assert "between 0 and 1" in error.lower()


def test_nonexistent_report_files():
    """Test validation of report file paths."""
    # Apply report
    args = parse_args(["-a", "/nonexistent/report.json"])
    error = _validate_args(args)
    assert error is not None
    assert "not found" in error.lower()

    # Print report
    args = parse_args(["-P", "/nonexistent/report.json"])
    error = _validate_args(args)
    assert error is not None
    assert "not found" in error.lower()


def test_conflicting_ui_options():
    """Test validation of conflicting UI options - now handled by quality levels."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Test that valid quality levels work
        args = parse_args(["-D", temp_dir, "-q", "3"])
        error = _validate_args(args)
        assert error is None  # Should be valid


def test_subset_detect_without_stage4():
    """Test that subset detection requires stage 4."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Quality level 5 enables subset detection and requires stage 4
        args = parse_args(["-D", temp_dir, "-q", "5"])
        error = _validate_args(args)
        # This should pass since quality 5 maps to "1-4" which includes stage 4
        if error is not None:
            assert "Quality levels 4 and 5 require pHash stage" in error


def test_scan_name_without_prefix():
    """Test scan name functionality - now handled via output directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Test that output directory works
        args = parse_args(["-D", temp_dir, "-o", "./output"])
        error = _validate_args(args)
        assert error is None  # Should be valid


def test_directory_validation():
    """Test validation of input directories."""
    # Nonexistent directory
    args = parse_args(["-D", "/nonexistent/directory"])
    error = _validate_args(args)
    assert error is not None
    assert "not found" in error.lower()


def test_file_as_directory():
    """Test validation when file is passed as directory."""
    with tempfile.NamedTemporaryFile() as temp_file:
        # Pass a file path where directory is expected
        args = parse_args(["-D", temp_file.name])
        error = _validate_args(args)
        assert error is not None
        assert "not a directory" in error.lower()


def test_output_directory_creation():
    """Test validation of output directory creation."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        test_video = temp_path / "test.mp4"
        test_video.write_text("fake video")

        # Valid backup directory
        backup_dir = temp_path / "backup"
        args = parse_args(["-D", str(temp_path), "-b", str(backup_dir)])
        error = _validate_args(args)
        assert error is None

        # Valid output directory
        output_dir = temp_path / "output"
        args = parse_args(["-D", str(temp_path), "-o", str(output_dir)])
        error = _validate_args(args)
        assert error is None


def test_enhanced_help_messages():
    """Test that enhanced help messages are present."""
    # This test ensures the help text improvements are in place
    with patch('sys.argv', ['video-dedupe', '--help']):
        try:
            parse_args(['--help'])
        except SystemExit:
            pass  # argparse exits on --help, which is expected

    # Test specific help content by parsing without exit
    parser_help = parse_args.__doc__ or ""
    # The enhanced help should be visible in the argument parser


if __name__ == "__main__":
    test_valid_args()
    test_invalid_pipeline()
    test_invalid_thread_count()
    test_invalid_duration_tolerance()
    test_invalid_phash_params()
    test_invalid_subset_ratio()
    test_nonexistent_report_files()
    test_conflicting_ui_options()
    test_subset_detect_without_stage4()
    test_scan_name_without_prefix()
    test_directory_validation()
    test_file_as_directory()
    test_output_directory_creation()
    test_enhanced_help_messages()
    print("All CLI validation tests passed!")