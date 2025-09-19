"""
Integration-style tests for the CLI entry point.

These tests ensure that the main CLI commands can be invoked with various flags
and don't crash due to argument parsing errors or miswiring to the runner.
The actual download process is mocked out.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Import the CLI main function to be tested
from ytaedl.cli import main as cli_main


@pytest.fixture
def mock_runner():
    """Fixture to patch the DownloadRunner and capture its instance."""
    with patch("ytaedl.cli.DownloadRunner") as mock_runner_class:
        # Create a mock instance that can be inspected
        mock_instance = MagicMock()
        mock_runner_class.return_value = mock_instance
        yield mock_instance


def make_url_file(tmp_path: Path, content: str = "http://example.com/video1") -> Path:
    """Helper to create a dummy URL file."""
    url_file = tmp_path / "urls.txt"
    url_file.write_text(content)
    return url_file


def test_cli_basic_run(tmp_path: Path, mock_runner: MagicMock):
    """Test a basic invocation with a URL file and output directory."""
    url_file = make_url_file(tmp_path)
    out_dir = tmp_path / "downloads"
    log_file = tmp_path / "activity.log"

    # Command line arguments
    args = [
        "-u", str(url_file),
        "-o", str(out_dir),
        "-L", str(log_file),
        "-j", "2",
    ]

    # Run the CLI
    return_code = cli_main(args)

    # Assertions
    assert return_code == 0
    mock_runner.run_from_files.assert_called_once()
    
    # Check that the runner was called with the correct high-level arguments
    call_args, call_kwargs = mock_runner.run_from_files.call_args
    assert call_args[0] == [url_file]  # url_files
    assert call_args[1] == out_dir      # base_out
    assert call_kwargs.get("per_file_subdirs") is True


def test_cli_no_ui_flag(tmp_path: Path, mock_runner: MagicMock):
    """Verify the --no-ui flag is passed correctly."""
    url_file = make_url_file(tmp_path)
    out_dir = tmp_path / "downloads"

    # Test with --no-ui
    with patch("ytaedl.cli.SimpleUI") as mock_simple_ui, patch("ytaedl.cli.TermdashUI") as mock_termdash_ui:
        args = ["-u", str(url_file), "-o", str(out_dir), "--no-ui"]
        return_code = cli_main(args)

        assert return_code == 0
        # Ensure the runner was initialized with the simple UI
        # This requires inspecting the arguments passed to the runner's constructor
        runner_constructor_args = mock_runner.__class__.call_args
        assert isinstance(runner_constructor_args.args[1], MagicMock)
        mock_termdash_ui.assert_not_called()


def test_cli_archive_file(tmp_path: Path, mock_runner: MagicMock):
    """Check if the archive file path is correctly configured."""
    url_file = make_url_file(tmp_path)
    out_dir = tmp_path / "downloads"
    archive_file = tmp_path / "archive.log"

    args = [
        "-u", str(url_file),
        "-o", str(out_dir),
        "-a", str(archive_file),
    ]
    
    cli_main(args)

    # Check that the DownloaderConfig passed to the runner has the correct archive path
    runner_constructor_args = mock_runner.__class__.call_args
    config_instance = runner_constructor_args.args[0]
    assert config_instance.archive_path == archive_file


def test_cli_aebn_only_flag(tmp_path: Path, mock_runner: MagicMock):
    """Ensure the --aebn-only flag is correctly passed to the config."""
    url_file = make_url_file(tmp_path, content="http://aebn.com/movie/123")
    out_dir = tmp_path / "downloads"

    args = ["-u", str(url_file), "-o", str(out_dir), "--aebn-only"]
    cli_main(args)

    runner_constructor_args = mock_runner.__class__.call_args
    config_instance = runner_constructor_args.args[0]
    assert config_instance.aebn_only is True
