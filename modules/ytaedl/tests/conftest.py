"""Pytest configuration and fixtures for ytaedl tests."""

import pytest
import tempfile
import os
from pathlib import Path


@pytest.fixture
def temp_dir():
    """Provide a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_url_file(temp_dir):
    """Create a sample URL file for testing."""
    url_file = temp_dir / "test_urls.txt"
    url_file.write_text("""
# Sample URL file for testing
https://example.com/video1
https://example.com/video2

# Comment line
https://example.com/video3  # inline comment
https://example.com/video4  ; another comment

; Full line comment
] Another comment style
https://example.com/video5
""".strip())
    return url_file


@pytest.fixture
def sample_empty_url_file(temp_dir):
    """Create an empty URL file for testing."""
    url_file = temp_dir / "empty.txt"
    url_file.write_text("")
    return url_file


@pytest.fixture
def sample_comment_only_url_file(temp_dir):
    """Create a URL file with only comments for testing."""
    url_file = temp_dir / "comments_only.txt"
    url_file.write_text("""
# Only comments here
; No actual URLs
] Just comments
""".strip())
    return url_file


@pytest.fixture
def mock_process():
    """Mock subprocess.Popen for testing without actually running processes."""
    from unittest.mock import MagicMock
    process = MagicMock()
    process.poll.return_value = None  # Still running
    process.stdout = iter([])  # Empty output
    process.terminate.return_value = None
    process.wait.return_value = 0
    return process


@pytest.fixture(autouse=True)
def reset_modules():
    """Reset any module-level state between tests."""
    yield
    # Any cleanup code can go here if needed


@pytest.fixture
def capture_output():
    """Capture stdout and stderr for testing output."""
    import io
    import sys
    from contextlib import contextmanager

    @contextmanager
    def _capture():
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        try:
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture
            yield stdout_capture, stderr_capture
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    return _capture


# Markers for different test types
def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests (may be slower)"
    )
    config.addinivalue_line(
        "markers", "unit: marks tests as unit tests (should be fast)"
    )


# Skip integration tests by default in CI environments
def pytest_collection_modifyitems(config, items):
    """Modify test collection to handle markers."""
    if config.getoption("--no-integration"):
        skip_integration = pytest.mark.skip(reason="--no-integration option given")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--no-integration",
        action="store_true",
        default=False,
        help="Skip integration tests"
    )