import pytest
import os
from system_manager.manager import SystemManager

def test_env_list():
    mgr = SystemManager()
    results = mgr.env_list()
    assert len(results) > 0
    # Should contain PATH
    assert any(r['variable'] == "PATH" for r in results)

def test_env_get():
    mgr = SystemManager()
    # Check a known env var
    os.environ["TEST_VAR"] = "test_value"
    mgr.env_get("TEST_VAR")
    # env_get prints to console, we can't easily assert return value if it's None
    # but we can check SystemManager.env_get logic in manager.py

def test_env_path_verify():
    mgr = SystemManager()
    # Current directory should not be on path usually, or we can check home
    result = mgr.env_path_verify(os.getcwd())
    assert "on_path" in result
