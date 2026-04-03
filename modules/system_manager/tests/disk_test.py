import pytest
import os
from system_manager.manager import SystemManager

def test_disk_usage():
    mgr = SystemManager()
    result = mgr.disk_usage(os.getcwd())
    assert "total" in result
    assert "percent" in result

def test_disk_free():
    mgr = SystemManager()
    results = mgr.disk_free()
    assert len(results) > 0
    assert "free" in results[0]

def test_disk_mounts():
    mgr = SystemManager()
    results = mgr.disk_mounts()
    assert len(results) > 0
    assert "mount" in results[0]
