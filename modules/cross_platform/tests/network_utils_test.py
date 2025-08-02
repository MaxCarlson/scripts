# tests/network_utils_test.py
import platform
import pytest
from unittest.mock import MagicMock

from cross_platform.network_utils import NetworkUtils

def fake_run_command_network_mock(self, command, sudo=False):
    # self is the NetworkUtils instance
    return f"fake output for: {command} with sudo={sudo}"

def test_network_reset_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(NetworkUtils, "run_command", fake_run_command_network_mock)
    
    net_utils = NetworkUtils()
    # Ensure is_termux is False for this Windows test if it could interfere
    monkeypatch.setattr(net_utils, "is_termux", lambda: False)
    output = net_utils.reset_network()
    
    assert "netsh winsock reset" in output
    assert "netsh int ip reset" in output
    assert "ipconfig /release" in output
    assert "ipconfig /renew" in output
    assert "ipconfig /flushdns" in output
    assert "sudo=True" not in output 

def test_network_reset_linux_normal(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(NetworkUtils, "run_command", fake_run_command_network_mock)
    
    net_utils = NetworkUtils() 
    monkeypatch.setattr(net_utils, "is_termux", lambda: False) 
    
    output = net_utils.reset_network()
    assert "systemctl restart NetworkManager" in output
    assert "sudo=True" in output

def test_network_reset_linux_termux(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    
    # Mock is_termux directly for reliable testing of this branch
    # rather than relying on multiple environment variables in SystemUtils.
    # SystemUtils might still be initialized, but we override is_termux on the instance.
    
    monkeypatch.setattr(NetworkUtils, "run_command", fake_run_command_network_mock)
    
    net_utils = NetworkUtils()
    # Explicitly set is_termux for this test case
    monkeypatch.setattr(net_utils, "is_termux", lambda: True)
    # Remove env var mocking if is_termux is directly mocked on the instance
    # monkeypatch.setenv("ANDROID_ROOT", "/data/data/com.termux")
    # monkeypatch.setenv("SHELL", "/data/data/com.termux/files/usr/bin/bash")
    
    output = net_utils.reset_network()
    
    assert "svc wifi disable && svc wifi enable" in output
    assert "sudo=True" in output

def test_network_reset_darwin(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(NetworkUtils, "run_command", fake_run_command_network_mock)
    
    net_utils = NetworkUtils()
    monkeypatch.setattr(net_utils, "is_termux", lambda: False) # Ensure Termux logic isn't triggered
    output = net_utils.reset_network()
    
    assert "ifconfig en0 down && ifconfig en0 up" in output
    assert "killall -HUP mDNSResponder" in output
    assert "sudo=True" in output

def test_network_reset_unsupported_os(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Solaris") 
    monkeypatch.setattr(NetworkUtils, "run_command", fake_run_command_network_mock)

    net_utils = NetworkUtils()
    monkeypatch.setattr(net_utils, "is_termux", lambda: False) # Ensure Termux logic isn't triggered
    output = net_utils.reset_network()
    
    assert output == ""
