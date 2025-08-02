import platform
import pytest
from unittest.mock import MagicMock

from cross_platform.process_manager import ProcessManager


def fake_run_command_process_mock(self, command, sudo=False):
    # self is ProcessManager instance
    if "tasklist" == command: return "windows_process_list"
    if "ps aux" == command: return "linux_darwin_process_list"
    if f"taskkill /IM my_process /F" == command : return "killed_windows_process"
    if f"pkill my_process" == command : return f"killed_linux_darwin_process_sudo_{sudo}"
    return f"unknown_command_{command}"

@pytest.fixture
def proc_mgr(monkeypatch):
    # Default to Linux for ProcessManager tests, individual tests can re-mock platform
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    # Mock run_command for all tests using this fixture
    monkeypatch.setattr(ProcessManager, "run_command", fake_run_command_process_mock)
    return ProcessManager()

def test_list_processes_windows(monkeypatch, proc_mgr):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    # Re-initialize or set os_name, __init__ depends on platform.system
    pm = ProcessManager() # Now os_name is 'windows'
    # proc_mgr.os_name = "windows" # Or set it directly if fixture is used and already init
    output = pm.list_processes()
    assert output == "windows_process_list"

def test_list_processes_linux(monkeypatch, proc_mgr):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    pm = ProcessManager()
    output = pm.list_processes()
    assert output == "linux_darwin_process_list"

def test_list_processes_darwin(monkeypatch, proc_mgr):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    pm = ProcessManager()
    output = pm.list_processes()
    assert output == "linux_darwin_process_list"

def test_kill_process_windows(monkeypatch, proc_mgr):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    pm = ProcessManager()
    output = pm.kill_process("my_process")
    assert output == "killed_windows_process"

def test_kill_process_linux(monkeypatch, proc_mgr):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    pm = ProcessManager()
    output = pm.kill_process("my_process")
    assert output == f"killed_linux_darwin_process_sudo_True" # sudo=True is default for kill

def test_kill_process_darwin(monkeypatch, proc_mgr):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    pm = ProcessManager()
    output = pm.kill_process("my_process")
    assert output == f"killed_linux_darwin_process_sudo_True"

def test_list_processes_unsupported(monkeypatch, proc_mgr):
    monkeypatch.setattr(platform, "system", lambda: "Solaris")
    pm = ProcessManager()
    output = pm.list_processes()
    assert output == ""

def test_kill_process_unsupported(monkeypatch, proc_mgr):
    monkeypatch.setattr(platform, "system", lambda: "Solaris")
    pm = ProcessManager()
    output = pm.kill_process("my_process")
    assert output == ""
