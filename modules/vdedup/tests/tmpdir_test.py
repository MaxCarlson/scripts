from pathlib import Path
import os


def test_tmp_path_uses_repo_basetemp(tmp_path):
    """
    Ensure tmp_path fixture respects the configured basetemp override.
    This guards against regressions where Windows refuses to create the default pytest temp root.
    """
    expected_root = Path(os.environ["VDEDUP_PYTEST_TMP_ROOT"]) / "basetemp"
    assert Path(tmp_path).resolve().is_relative_to(expected_root.resolve())
