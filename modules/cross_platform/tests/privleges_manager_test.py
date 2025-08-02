# tests/privileges_manager_test.py
import os
import platform
import pytest
from unittest.mock import MagicMock
import sys

from cross_platform.privileges_manager import PrivilegesManager

@pytest.fixture
def priv_mgr_linux(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    return PrivilegesManager()

@pytest.fixture
def priv_mgr_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    return PrivilegesManager()

def test_require_admin_linux_success(monkeypatch, priv_mgr_linux):
    monkeypatch.setattr(os, "geteuid", lambda: 0) # Running as root
    priv_mgr_linux.require_admin() # Should not raise

def test_require_admin_linux_failure(monkeypatch, priv_mgr_linux):
    monkeypatch.setattr(os, "geteuid", lambda: 1) # Not running as root
    with pytest.raises(PermissionError, match="Administrator \\(root\\) privileges required."):
        priv_mgr_linux.require_admin()

def test_require_admin_darwin_success(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    priv_mgr = PrivilegesManager()
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    priv_mgr.require_admin()

def test_require_admin_darwin_failure(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    priv_mgr = PrivilegesManager()
    monkeypatch.setattr(os, "geteuid", lambda: 1)
    with pytest.raises(PermissionError, match="Administrator \\(root\\) privileges required."):
        priv_mgr.require_admin()

@pytest.fixture
def mock_ctypes(monkeypatch):
    # Ensure sys is available (already imported at module level)
    # import sys 

    # Create the mock for IsUserAnAdmin function first
    # This is the actual function/method we want to control in the tests.
    mock_is_user_an_admin_func = MagicMock(return_value=False) 

    # Create the hierarchy of mocks for ctypes.windll.shell32.IsUserAnAdmin
    mock_shell32 = MagicMock(name="MockShell32")
    mock_shell32.IsUserAnAdmin = mock_is_user_an_admin_func # Attach the function mock

    mock_windll = MagicMock(name="MockWindll")
    mock_windll.shell32 = mock_shell32

    mock_ctypes_module = MagicMock(name="MockCtypesModule")
    mock_ctypes_module.windll = mock_windll
    mock_ctypes_module.WinError = OSError # Mock other attributes if needed by source

    # Patch sys.modules. When 'privileges_manager' imports ctypes, it gets our mock.
    monkeypatch.setitem(sys.modules, 'ctypes', mock_ctypes_module)
    
    # The test will access this module: mock_ctypes_module.windll.shell32.IsUserAnAdmin
    # which will resolve to mock_is_user_an_admin_func
    return mock_ctypes_module


def test_require_admin_windows_success(mock_ctypes, priv_mgr_windows):
    # mock_ctypes is mock_ctypes_module from the fixture.
    # mock_ctypes.windll.shell32.IsUserAnAdmin is mock_is_user_an_admin_func.
    mock_ctypes.windll.shell32.IsUserAnAdmin.return_value = 1 # Simulate admin
    priv_mgr_windows.require_admin() # Should not raise

def test_require_admin_windows_failure_not_admin(mock_ctypes, priv_mgr_windows):
    mock_ctypes.windll.shell32.IsUserAnAdmin.return_value = 0 # Simulate not admin
    with pytest.raises(PermissionError, match="Administrator privileges required."):
        priv_mgr_windows.require_admin()

def test_require_admin_windows_failure_ctypes_error(mock_ctypes, priv_mgr_windows):
    # mock_ctypes.windll.shell32.IsUserAnAdmin is mock_is_user_an_admin_func
    # which is a MagicMock, so .side_effect can be set.
    mock_ctypes.windll.shell32.IsUserAnAdmin.side_effect = Exception("ctypes call failed")

    with pytest.raises(PermissionError, match="Administrator privileges required."):
        priv_mgr_windows.require_admin()

def test_require_admin_unsupported_os(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Solaris")
    priv_mgr = PrivilegesManager()
    with pytest.raises(PermissionError, match="Unsupported OS for privilege checking."):
        priv_mgr.require_admin()
