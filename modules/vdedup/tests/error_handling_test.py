#!/usr/bin/env python3
"""
Tests for enhanced error handling across modules.
"""
import tempfile
import os
import subprocess
from pathlib import Path
from unittest.mock import patch, Mock

from vdedup.probe import run_ffprobe_json
from vdedup.hashers import sha256_file, partial_hash


def test_probe_nonexistent_file():
    """Test ffprobe handling of nonexistent files."""
    nonexistent = Path("/nonexistent/file.mp4")
    result = run_ffprobe_json(nonexistent)
    assert result is None


def test_probe_empty_path():
    """Test ffprobe handling of empty/None paths."""
    result = run_ffprobe_json(None)
    assert result is None

    result = run_ffprobe_json(Path(""))
    assert result is None


def test_probe_timeout_handling():
    """Test that ffprobe handles timeouts gracefully."""
    with tempfile.NamedTemporaryFile(suffix=".mp4") as temp_file:
        temp_path = Path(temp_file.name)

        # Mock subprocess.run to simulate timeout
        with patch('vdedup.probe.subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=[], timeout=30)

            result = run_ffprobe_json(temp_path)
            assert result is None


def test_probe_invalid_json():
    """Test ffprobe handling of invalid JSON output."""
    with tempfile.NamedTemporaryFile(suffix=".mp4") as temp_file:
        temp_path = Path(temp_file.name)

        # Mock subprocess.run to return invalid JSON
        with patch('vdedup.probe.subprocess.run') as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = "invalid json {"
            mock_run.return_value = mock_result

            result = run_ffprobe_json(temp_path)
            assert result is None


def test_sha256_nonexistent_file():
    """Test SHA-256 handling of nonexistent files."""
    nonexistent = Path("/nonexistent/file.txt")
    result = sha256_file(nonexistent)
    assert result is None


def test_sha256_empty_file():
    """Test SHA-256 handling of empty files."""
    with tempfile.NamedTemporaryFile() as temp_file:
        temp_path = Path(temp_file.name)
        # File is created but empty

        result = sha256_file(temp_path)
        assert result is not None
        # Empty file should have a specific hash
        assert len(result) == 64  # SHA-256 hex length


def test_sha256_directory():
    """Test SHA-256 handling when path is a directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        dir_path = Path(temp_dir)

        result = sha256_file(dir_path)
        assert result is None


def test_sha256_permission_error():
    """Test SHA-256 handling of permission errors."""
    with tempfile.NamedTemporaryFile() as temp_file:
        temp_path = Path(temp_file.name)
        temp_file.write(b"test content")
        temp_file.flush()

        # Mock both exists and open to simulate permission error
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'is_file', return_value=True), \
             patch.object(Path, 'stat') as mock_stat, \
             patch.object(Path, 'open') as mock_open:

            # Mock stat to return valid size
            mock_stat.return_value.st_size = 100
            mock_open.side_effect = PermissionError("Access denied")

            result = sha256_file(temp_path)
            assert result is None


def test_partial_hash_nonexistent_file():
    """Test partial hash handling of nonexistent files."""
    nonexistent = Path("/nonexistent/file.bin")
    result = partial_hash(nonexistent)
    assert result is None


def test_partial_hash_empty_file():
    """Test partial hash handling of empty files."""
    with tempfile.NamedTemporaryFile() as temp_file:
        temp_path = Path(temp_file.name)
        # File is created but empty

        result = partial_hash(temp_path)
        assert result is None  # Empty files should return None


def test_partial_hash_invalid_parameters():
    """Test partial hash handling of invalid parameters."""
    with tempfile.NamedTemporaryFile() as temp_file:
        temp_path = Path(temp_file.name)
        temp_file.write(b"some test content")
        temp_file.flush()

        # Test negative byte counts
        result = partial_hash(temp_path, head_bytes=-1)
        assert result is None

        result = partial_hash(temp_path, tail_bytes=-1)
        assert result is None

        result = partial_hash(temp_path, mid_bytes=-1)
        assert result is None


def test_partial_hash_small_file():
    """Test partial hash handling of files smaller than requested bytes."""
    import tempfile
    import os

    # Create a temporary file manually to avoid Windows file locking
    temp_dir = tempfile.mkdtemp()
    temp_path = Path(temp_dir) / "test_small.bin"

    try:
        small_content = b"small"
        temp_path.write_bytes(small_content)

        # Request more bytes than file contains
        result = partial_hash(temp_path, head_bytes=1000, tail_bytes=1000)
        assert result is not None

        head_hash, tail_hash, mid_hash, algo = result
        assert isinstance(head_hash, str)
        assert isinstance(tail_hash, str)
        assert mid_hash is None  # Should be None for small file
        assert algo in ["blake3", "blake2b"]

        # For small files, head and tail should be the same
        assert head_hash == tail_hash

    finally:
        if temp_path.exists():
            temp_path.unlink()
        os.rmdir(temp_dir)


def test_partial_hash_memory_error():
    """Test partial hash handling of memory errors."""
    with tempfile.NamedTemporaryFile() as temp_file:
        temp_path = Path(temp_file.name)
        temp_file.write(b"test content")
        temp_file.flush()

        # Mock open to raise MemoryError
        with patch('pathlib.Path.open') as mock_open:
            mock_open.side_effect = MemoryError("Out of memory")

            result = partial_hash(temp_path)
            assert result is None


def test_partial_hash_directory():
    """Test partial hash handling when path is a directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        dir_path = Path(temp_dir)

        result = partial_hash(dir_path)
        assert result is None


if __name__ == "__main__":
    import subprocess

    test_probe_nonexistent_file()
    test_probe_empty_path()
    test_sha256_nonexistent_file()
    test_sha256_empty_file()
    test_sha256_directory()
    test_partial_hash_nonexistent_file()
    test_partial_hash_empty_file()
    test_partial_hash_invalid_parameters()
    test_partial_hash_small_file()
    test_partial_hash_directory()
    print("All error handling tests passed!")