import pytest
import shutil
from system_manager.manager import SystemManager

@pytest.mark.skipif(not shutil.which("git"), reason="Git not installed")
def test_git_status_short():
    mgr = SystemManager()
    results = mgr.git_status_short()
    assert isinstance(results, list)

@pytest.mark.skipif(not shutil.which("git"), reason="Git not installed")
def test_git_branch_info():
    mgr = SystemManager()
    result = mgr.git_branch_info()
    assert "branch" in result
    assert "commit" in result

@pytest.mark.skipif(not shutil.which("git"), reason="Git not installed")
def test_git_root():
    mgr = SystemManager()
    result = mgr.git_root()
    assert "root" in result
