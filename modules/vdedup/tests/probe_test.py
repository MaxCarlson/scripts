#!/usr/bin/env python3
"""
Tests for vdedup.probe module (ffprobe integration).

Tests cover:
- Successful metadata extraction
- Error handling (missing files, corrupted files, timeouts)
- Field validation (ensures only requested fields are returned)
- Performance characteristics
"""

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from vdedup.probe import run_ffprobe_json


class TestRunFFProbeJson:
    """Tests for run_ffprobe_json function."""

    def test_nonexistent_file_returns_none(self):
        """Non-existent file should return None."""
        result = run_ffprobe_json(Path("/nonexistent/file.mp4"))
        assert result is None

    def test_none_path_returns_none(self):
        """None path should return None."""
        result = run_ffprobe_json(None)  # type: ignore
        assert result is None

    @patch('subprocess.run')
    def test_successful_probe_returns_json(self, mock_run):
        """Successful ffprobe should return parsed JSON."""
        # Mock successful ffprobe output
        mock_output = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "24/1",
                    "bit_rate": "5000000"
                }
            ],
            "format": {
                "duration": "120.5",
                "format_name": "mp4",
                "bit_rate": "6000000"
            }
        }

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(mock_output)
        )

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            test_file = Path(f.name)

        try:
            result = run_ffprobe_json(test_file)

            assert result is not None
            assert "streams" in result
            assert "format" in result
            assert result["streams"][0]["codec_name"] == "h264"
            assert result["streams"][0]["width"] == 1920
            assert result["format"]["duration"] == "120.5"
        finally:
            test_file.unlink()

    @patch('subprocess.run')
    def test_ffprobe_error_returns_none(self, mock_run):
        """ffprobe error (non-zero return code) should return None."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error: Invalid file"
        )

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            test_file = Path(f.name)

        try:
            result = run_ffprobe_json(test_file)
            assert result is None
        finally:
            test_file.unlink()

    @patch('subprocess.run')
    def test_timeout_returns_none(self, mock_run):
        """ffprobe timeout should return None (not raise exception)."""
        mock_run.side_effect = subprocess.TimeoutExpired("ffprobe", 30)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            test_file = Path(f.name)

        try:
            result = run_ffprobe_json(test_file)
            assert result is None
        finally:
            test_file.unlink()

    @patch('subprocess.run')
    def test_invalid_json_returns_none(self, mock_run):
        """Invalid JSON output should return None."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="not valid json{[}]"
        )

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            test_file = Path(f.name)

        try:
            result = run_ffprobe_json(test_file)
            assert result is None
        finally:
            test_file.unlink()

    @patch('subprocess.run')
    def test_empty_output_returns_none(self, mock_run):
        """Empty ffprobe output should return None."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=""
        )

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            test_file = Path(f.name)

        try:
            result = run_ffprobe_json(test_file)
            assert result is None
        finally:
            test_file.unlink()

    @patch('subprocess.run')
    def test_whitespace_only_output_returns_none(self, mock_run):
        """Whitespace-only output should return None."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="   \n\t  "
        )

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            test_file = Path(f.name)

        try:
            result = run_ffprobe_json(test_file)
            assert result is None
        finally:
            test_file.unlink()

    @patch('subprocess.run')
    def test_command_uses_optimized_flags(self, mock_run):
        """Verify ffprobe command uses optimized flags."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"streams": [], "format": {}})
        )

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            test_file = Path(f.name)

        try:
            run_ffprobe_json(test_file)

            # Verify subprocess.run was called
            assert mock_run.called

            # Get the command that was called
            cmd = mock_run.call_args[0][0]

            # Verify optimizations:
            # 1. Uses -select_streams v:0 for first video stream only
            assert "-select_streams" in cmd
            assert "v:0" in cmd

            # 2. Uses minimal field selection
            assert "-show_entries" in cmd

            # 3. Requests only needed fields
            entries_str = " ".join(cmd)
            assert "stream=width,height,codec_name,r_frame_rate,bit_rate,codec_type" in entries_str
            assert "format=duration,format_name,bit_rate" in entries_str

            # 4. Uses JSON output format
            assert "-of" in cmd
            assert "json" in cmd

            # 5. Error suppression
            assert "-v" in cmd
            assert "error" in cmd

        finally:
            test_file.unlink()

    @patch('subprocess.run')
    def test_timeout_is_set(self, mock_run):
        """Verify subprocess.run uses timeout parameter."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"streams": [], "format": {}})
        )

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            test_file = Path(f.name)

        try:
            run_ffprobe_json(test_file)

            # Verify timeout was set
            assert mock_run.call_args[1].get("timeout") == 30

        finally:
            test_file.unlink()

    @patch('subprocess.run')
    def test_handles_permission_error(self, mock_run):
        """PermissionError should be caught and return None."""
        mock_run.side_effect = PermissionError("Access denied")

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            test_file = Path(f.name)

        try:
            result = run_ffprobe_json(test_file)
            assert result is None
        finally:
            test_file.unlink()

    @patch('subprocess.run')
    def test_handles_file_not_found_error(self, mock_run):
        """FileNotFoundError (ffprobe not installed) should be caught."""
        mock_run.side_effect = FileNotFoundError("ffprobe not found")

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            test_file = Path(f.name)

        try:
            result = run_ffprobe_json(test_file)
            assert result is None
        finally:
            test_file.unlink()

    @patch('subprocess.run')
    def test_returns_all_expected_fields(self, mock_run):
        """Verify all expected fields are present in successful response."""
        mock_output = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h265",
                    "width": 3840,
                    "height": 2160,
                    "r_frame_rate": "60/1",
                    "bit_rate": "15000000"
                }
            ],
            "format": {
                "duration": "300.25",
                "format_name": "matroska,webm",
                "bit_rate": "18000000"
            }
        }

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(mock_output)
        )

        with tempfile.NamedTemporaryFile(suffix=".mkv", delete=False) as f:
            test_file = Path(f.name)

        try:
            result = run_ffprobe_json(test_file)

            # Verify structure
            assert result is not None
            assert "streams" in result
            assert "format" in result

            # Verify stream fields
            stream = result["streams"][0]
            assert "codec_type" in stream
            assert "codec_name" in stream
            assert "width" in stream
            assert "height" in stream
            assert "r_frame_rate" in stream
            assert "bit_rate" in stream

            # Verify format fields
            fmt = result["format"]
            assert "duration" in fmt
            assert "format_name" in fmt
            assert "bit_rate" in fmt

            # Verify values
            assert stream["width"] == 3840
            assert stream["height"] == 2160
            assert stream["codec_name"] == "h265"
            assert fmt["duration"] == "300.25"

        finally:
            test_file.unlink()

    @patch('subprocess.run')
    def test_unexpected_exception_returns_none(self, mock_run):
        """Any unexpected exception should be caught and return None."""
        mock_run.side_effect = RuntimeError("Unexpected error")

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            test_file = Path(f.name)

        try:
            result = run_ffprobe_json(test_file)
            assert result is None
        finally:
            test_file.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
