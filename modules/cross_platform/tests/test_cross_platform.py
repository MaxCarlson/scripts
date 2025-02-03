import os
import subprocess
import platform
import pytest
from cross_platform.system_utils import SystemUtils
from cross_platform.network_utils import NetworkUtils
from cross_platform.process_manager import ProcessManager
from cross_platform.privileges_manager import PrivilegesManager
from cross_platform.clipboard_utils import ClipboardUtils
from cross_platform.debug_utils import write_debug, set_console_verbosity, _validate_verbosity_level

# -----------------------
# Tests for system_utils.py
# -----------------------

def fake_platform_system():
    return "Linux"

def test_system_utils_os_detection(monkeypatch):
    # Override platform.system to return Linux
    monkeypatch.setattr(platform, "system", fake_platform_system)
    sys_utils = SystemUtils()
    assert sys_utils.os_name == "linux"

def test_is_termux(monkeypatch):
    # Set up environment variables to simulate Termux
    monkeypatch.setenv("ANDROID_ROOT", "/data/data/com.termux")
    monkeypatch.setenv("SHELL", "/data/data/com.termux/files/usr/bin/bash")
    sys_utils = SystemUtils()
    assert sys_utils.is_termux() is True

def test_run_command_success(monkeypatch):
    sys_utils = SystemUtils()
    # Use a command that should work on most systems.
    output = sys_utils.run_command("echo test")
    assert "test" in output

# -----------------------
# Tests for network_utils.py
# -----------------------

def fake_run_command_network(self, command, sudo=False):
    # A fake run_command that returns a string based on the input command.
    return f"fake output for: {command}"

def test_network_reset_windows(monkeypatch):
    monkeypatch.setattr(NetworkUtils, "run_command", fake_run_command_network)
    net_utils = NetworkUtils()
    net_utils.os_name = "windows"
    output = net_utils.reset_network()
    assert "netsh winsock reset" in output

def test_network_reset_linux(monkeypatch):
    monkeypatch.setattr(NetworkUtils, "run_command", fake_run_command_network)
    net_utils = NetworkUtils()
    net_utils.os_name = "linux"
    output = net_utils.reset_network()
    assert "systemctl restart NetworkManager" in output

# -----------------------
# Tests for process_manager.py
# -----------------------

def fake_run_command_process(self, command, sudo=False):
    if "tasklist" in command or "ps aux" in command:
        return "fake process list"
    elif "taskkill" in command or "pkill" in command:
        return "killed process"
    return ""

def test_list_processes(monkeypatch):
    monkeypatch.setattr(ProcessManager, "run_command", fake_run_command_process)
    proc_mgr = ProcessManager()
    # Simulate Windows
    proc_mgr.os_name = "windows"
    output = proc_mgr.list_processes()
    assert "fake process list" in output

def test_kill_process(monkeypatch):
    monkeypatch.setattr(ProcessManager, "run_command", fake_run_command_process)
    proc_mgr = ProcessManager()
    proc_mgr.os_name = "linux"
    output = proc_mgr.kill_process("dummy_process")
    # Instead of checking for 'pkill' in output, we now check the fake return string.
    assert output == "killed process"

# -----------------------
# Tests for privileges_manager.py
# -----------------------

def test_require_admin_linux_success(monkeypatch):
    # Monkey-patch os.geteuid to simulate running as root
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    priv_mgr = PrivilegesManager()
    priv_mgr.os_name = "linux"
    # Should not raise an exception
    priv_mgr.require_admin()

def test_require_admin_linux_failure(monkeypatch):
    # Simulate non-root environment (e.g. geteuid != 0)
    monkeypatch.setattr(os, "geteuid", lambda: 1)
    priv_mgr = PrivilegesManager()
    priv_mgr.os_name = "linux"
    with pytest.raises(PermissionError):
        priv_mgr.require_admin()

# -----------------------
# Tests for clipboard_utils.py
# -----------------------

def fake_run_command_clipboard(self, command, sudo=False):
    # Return outputs based on expected command content
    if "termux-clipboard-get" in command:
        return "termux clipboard"
    if "xclip" in command:
        return "linux clipboard"
    if "pbpaste" in command:
        return "macos clipboard"
    if "Get-Clipboard" in command:
        return "windows clipboard"
    return ""

def test_get_clipboard_linux(monkeypatch):
    monkeypatch.setattr(ClipboardUtils, "run_command", fake_run_command_clipboard)
    cp = ClipboardUtils()
    cp.os_name = "linux"
    # Ensure is_wsl2 returns False so that Linux branch is used.
    monkeypatch.setattr(cp, "is_wsl2", lambda: False)
    result = cp.get_clipboard()
    assert result == "linux clipboard"

def test_get_clipboard_windows(monkeypatch):
    monkeypatch.setattr(ClipboardUtils, "run_command", fake_run_command_clipboard)
    cp = ClipboardUtils()
    cp.os_name = "windows"
    # Force is_wsl2() to return False so the Windows branch is taken.
    monkeypatch.setattr(cp, "is_wsl2", lambda: False)
    result = cp.get_clipboard()
    assert result == "windows clipboard"

def test_set_clipboard_windows(monkeypatch):
    # To test set_clipboard we override subprocess.run
    captured = {}

    def fake_subprocess_run(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr("cross_platform.clipboard_utils.subprocess.run", fake_subprocess_run)
    cp = ClipboardUtils()
    cp.os_name = "windows"
    monkeypatch.setattr(cp, "is_wsl2", lambda: False)
    cp.set_clipboard("test text")
    # Check that the command contains Set-Clipboard
    assert any("Set-Clipboard" in arg for arg in captured["args"])

# -----------------------
# Tests for debug_utils.py
# -----------------------

def test_write_debug_stdout(capsys):
    # Clear any file logging to only capture console output.
    write_debug("Test debug message", channel="Debug", location_channels=False)
    captured = capsys.readouterr().out
    assert "Test debug message" in captured

def test_invalid_verbosity_level():
    with pytest.raises(ValueError):
        _validate_verbosity_level("invalid", "console")
