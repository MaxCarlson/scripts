"""Pytest configuration and fixtures for ytaedl tests."""

import os
import sys
from itertools import count
from pathlib import Path
import tempfile

import pytest

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_ROOT))
os.chdir(_PACKAGE_ROOT)

_TMP_COUNTER = count(1)
# On Windows, the system-level pytest-of-<user> directory in %TEMP% can become
# inaccessible (Access Denied on os.scandir) if its mode bits get misconfigured.
# Redirect pytest to a module-local temp root so test scratch directories do
# not litter the repository root.
_WIN_TEMP_ROOT: Path | None = None

if sys.platform == "win32":
    _default_temp_root = (
        _PACKAGE_ROOT
        / ".pytest_tmp_root"
        / f"ytaedl-temp-{os.getpid()}"
    )
    _candidate_temproots = [
        Path(os.environ["YTAEDL_PYTEST_TEMPROOT"])
        if "YTAEDL_PYTEST_TEMPROOT" in os.environ
        else None,
        _default_temp_root,
    ]
    for _local_temproot in [p for p in _candidate_temproots if p is not None]:
        try:
            _local_temproot.mkdir(parents=True, exist_ok=True)
            (_local_temproot / "probe.tmp").write_text("ok", encoding="utf-8")
            _root = str(_local_temproot)
            os.environ["PYTEST_DEBUG_TEMPROOT"] = _root
            os.environ["TMP"] = _root
            os.environ["TEMP"] = _root
            tempfile.tempdir = _root
            _WIN_TEMP_ROOT = _local_temproot
            break
        except OSError:
            continue


def _make_test_temp_dir(prefix: str) -> Path:
    """Create a unique test temp directory without relying on cleanup hooks."""
    root = _WIN_TEMP_ROOT or Path(tempfile.gettempdir())
    root.mkdir(parents=True, exist_ok=True)
    while True:
        path = root / f"{prefix}_{next(_TMP_COUNTER):04d}"
        try:
            path.mkdir(parents=True, exist_ok=False)
            return path
        except FileExistsError:
            continue


class _WorkspaceTemporaryDirectory:
    """Small TemporaryDirectory stand-in that avoids Windows cleanup failures."""

    def __init__(self, *args, **kwargs):
        prefix = kwargs.get("prefix") or "tmp"
        self.name = str(_make_test_temp_dir(prefix.rstrip("_")))

    def __enter__(self):
        return self.name

    def __exit__(self, exc_type, exc, tb):
        return False

    def cleanup(self):
        return None


def _workspace_temporary_directory(*args, **kwargs):
    """Route legacy TemporaryDirectory calls into the writable test root."""
    return _WorkspaceTemporaryDirectory(*args, **kwargs)


if sys.platform == "win32" and _WIN_TEMP_ROOT is not None:
    tempfile.TemporaryDirectory = _workspace_temporary_directory


@pytest.fixture(autouse=True, scope="session")
def _force_writable_temp_root():
    """Keep legacy tempfile.TemporaryDirectory tests off broken Windows temp roots."""
    if sys.platform == "win32":
        root = _WIN_TEMP_ROOT or Path(os.environ.get("YTAEDL_PYTEST_TEMPROOT") or os.environ.get("TMP") or "")
        if not root:
            root = (
                _PACKAGE_ROOT
                / ".pytest_tmp_root"
                / f"ytaedl-temp-{os.getpid()}"
            )
        root.mkdir(parents=True, exist_ok=True)
        os.environ["PYTEST_DEBUG_TEMPROOT"] = str(root)
        os.environ["TMP"] = str(root)
        os.environ["TEMP"] = str(root)
        tempfile.tempdir = str(root)


@pytest.fixture
def tmp_path():
    """Workspace-local replacement for pytest tmp_path on Windows ACL-hostile runs."""
    yield _make_test_temp_dir("tmp_path")


@pytest.fixture
def temp_dir():
    """Provide a temporary directory for tests."""
    yield _make_test_temp_dir("temp_dir")


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


def pytest_configure(config):
    """Configure pytest markers and temp roots."""
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
