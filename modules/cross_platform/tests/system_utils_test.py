import os
import subprocess
import platform
import pytest
from unittest.mock import MagicMock

from cross_platform.system_utils import SystemUtils

def fake_platform_system_linux():
    return "Linux"

def fake_platform_system_windows():
    return "Windows"

def test_system_utils_os_detection(monkeypatch):
    monkeypatch.setattr(platform, "system", fake_platform_system_linux)
    sys_utils = SystemUtils()
    assert sys_utils.os_name == "linux"

def test_is_termux_true(monkeypatch):
    monkeypatch.setenv("ANDROID_ROOT", "/data/data/com.termux")
    monkeypatch.setenv("SHELL", "/data/data/com.termux/files/usr/bin/bash")
    # SystemUtils reads os.environ on init for is_wsl2 via platform.uname(),
    # ensure platform.system is something reasonable for SystemUtils init
    monkeypatch.setattr(platform, "system", fake_platform_system_linux)
    sys_utils = SystemUtils()
    assert sys_utils.is_termux() is True

def test_is_termux_false_no_android_root(monkeypatch):
    monkeypatch.delenv("ANDROID_ROOT", raising=False)
    monkeypatch.setenv("SHELL", "/data/data/com.termux/files/usr/bin/bash")
    monkeypatch.setattr(platform, "system", fake_platform_system_linux)
    sys_utils = SystemUtils()
    assert sys_utils.is_termux() is False

def test_is_termux_false_wrong_shell(monkeypatch):
    monkeypatch.setenv("ANDROID_ROOT", "/data/data/com.termux")
    monkeypatch.setenv("SHELL", "/usr/bin/bash")
    monkeypatch.setattr(platform, "system", fake_platform_system_linux)
    sys_utils = SystemUtils()
    assert sys_utils.is_termux() is False

def test_run_command_success(monkeypatch):
    # Mock subprocess.run to avoid actual command execution
    mock_completed_process = subprocess.CompletedProcess(args="echo test", returncode=0, stdout="test\n", stderr="")
    mock_sub_run = MagicMock(return_value=mock_completed_process)
    monkeypatch.setattr(subprocess, "run", mock_sub_run)
    
    monkeypatch.setattr(platform, "system", fake_platform_system_linux)
    sys_utils = SystemUtils()
    output = sys_utils.run_command("echo test")
    
    assert "test" in output
    mock_sub_run.assert_called_once_with("echo test", shell=True, text=True, capture_output=True)

def test_run_command_failure(monkeypatch):
    mock_completed_process = subprocess.CompletedProcess(args="failing_cmd", returncode=1, stdout="", stderr="error")
    mock_sub_run = MagicMock(return_value=mock_completed_process)
    monkeypatch.setattr(subprocess, "run", mock_sub_run)

    monkeypatch.setattr(platform, "system", fake_platform_system_linux)
    sys_utils = SystemUtils()
    output = sys_utils.run_command("failing_cmd")
    
    assert output == "" # Expect empty string on failure
    mock_sub_run.assert_called_once_with("failing_cmd", shell=True, text=True, capture_output=True)

def test_run_command_exception(monkeypatch):
    mock_sub_run = MagicMock(side_effect=Exception("Command execution failed"))
    monkeypatch.setattr(subprocess, "run", mock_sub_run)

    monkeypatch.setattr(platform, "system", fake_platform_system_linux)
    sys_utils = SystemUtils()
    output = sys_utils.run_command("some_cmd")

    assert output == "" # Expect empty string on exception
    mock_sub_run.assert_called_once_with("some_cmd", shell=True, text=True, capture_output=True)


def test_source_file_success_linux(monkeypatch):
    monkeypatch.setattr(platform, "system", fake_platform_system_linux)
    sys_utils = SystemUtils()
    monkeypatch.setattr(sys_utils, "is_termux", lambda: False)
    
    mock_completed_process = subprocess.CompletedProcess(args=["zsh", "-c", "source /fake/path/to/file.zsh"], returncode=0, stdout="ok", stderr="")
    mock_sub_run = MagicMock(return_value=mock_completed_process)
    monkeypatch.setattr(subprocess, "run", mock_sub_run)
    
    result = sys_utils.source_file("/fake/path/to/file.zsh")
    assert result is True
    mock_sub_run.assert_called_once_with(["zsh", "-c", "source /fake/path/to/file.zsh"], text=True, capture_output=True)

def test_source_file_failure_linux(monkeypatch):
    monkeypatch.setattr(platform, "system", fake_platform_system_linux)
    sys_utils = SystemUtils()
    monkeypatch.setattr(sys_utils, "is_termux", lambda: False)

    mock_completed_process = subprocess.CompletedProcess(args=["zsh", "-c", "source /fake/path/to/file.zsh"], returncode=1, stdout="", stderr="error")
    mock_sub_run = MagicMock(return_value=mock_completed_process)
    monkeypatch.setattr(subprocess, "run", mock_sub_run)
    
    result = sys_utils.source_file("/fake/path/to/file.zsh")
    assert result is False

def test_source_file_exception_linux(monkeypatch):
    monkeypatch.setattr(platform, "system", fake_platform_system_linux)
    sys_utils = SystemUtils()
    monkeypatch.setattr(sys_utils, "is_termux", lambda: False)
    
    mock_sub_run = MagicMock(side_effect=Exception("boom"))
    monkeypatch.setattr(subprocess, "run", mock_sub_run)
    
    result = sys_utils.source_file("/fake/path/to/file.zsh")
    assert result is False

def test_source_file_not_supported_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", fake_platform_system_windows)
    sys_utils = SystemUtils()
    # is_termux is irrelevant if OS is Windows for this method
    result = sys_utils.source_file("/fake/path/to/file.zsh")
    assert result is False

def test_source_file_not_supported_termux(monkeypatch):
    monkeypatch.setattr(platform, "system", fake_platform_system_linux) # Termux runs on Linux-like
    sys_utils = SystemUtils()
    monkeypatch.setattr(sys_utils, "is_termux", lambda: True)
    result = sys_utils.source_file("/fake/path/to/file.zsh")
    assert result is False
