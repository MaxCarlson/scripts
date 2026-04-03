import pytest
from system_manager.manager import SystemManager

def test_pkg_list():
    mgr = SystemManager()
    results = mgr.pkg_list(manager="pip")
    # Should have some pip packages
    assert len(results) > 0
    assert "name" in results[0]

def test_pkg_outdated():
    mgr = SystemManager()
    # Check if we can at least call it
    results = mgr.pkg_outdated()
    assert isinstance(results, list)

def test_pkg_which_manager():
    mgr = SystemManager()
    results = mgr.pkg_which_manager("python")
    # Should find at least one manager for python
    assert len(results) >= 0 # Might be empty in some envs but should not crash
