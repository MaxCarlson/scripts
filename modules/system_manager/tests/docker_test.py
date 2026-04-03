import pytest
import shutil
from system_manager.manager import SystemManager

@pytest.mark.skipif(not shutil.which("docker"), reason="Docker not installed")
def test_docker_ps():
    mgr = SystemManager()
    results = mgr.docker_ps()
    assert isinstance(results, list)

@pytest.mark.skipif(not shutil.which("docker"), reason="Docker not installed")
def test_docker_images():
    mgr = SystemManager()
    results = mgr.docker_images()
    assert isinstance(results, list)
