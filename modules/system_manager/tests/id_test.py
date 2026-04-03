import pytest
from system_manager.manager import SystemManager

def test_whoami():
    mgr = SystemManager()
    result = mgr.whoami()
    assert "property" in result
    assert "value" in result
    assert "Username" in result["property"]

def test_id_hostname():
    mgr = SystemManager()
    result = mgr.id_hostname()
    assert "hostname" in result
    assert "fqdn" in result

def test_id_admin_check():
    mgr = SystemManager()
    result = mgr.id_admin_check()
    assert "elevated" in result
    assert isinstance(result["elevated"], bool)

def test_id_sessions():
    mgr = SystemManager()
    results = mgr.id_sessions()
    # Should have at least the current user session
    assert len(results) > 0
    assert "user" in results[0]
