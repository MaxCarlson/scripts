from pathlib import Path


def test_tmp_path_uses_repo_basetemp(tmp_path):
    """
    Ensure tmp_path fixture respects the repository-scoped basetemp override.
    This guards against regressions where Windows refuses to create %LOCALAPPDATA%\\pytest-of-*.
    """
    expected_root = Path(__file__).resolve().parent / ".pytest_tmp" / "basetemp"
    assert Path(tmp_path).resolve().is_relative_to(expected_root.resolve())
