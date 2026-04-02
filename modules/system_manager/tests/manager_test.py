import pytest
from system_manager.manager import SystemManager

def test_whoami(capsys):
    SystemManager.whoami()
    captured = capsys.readouterr()
    assert "Identity Info" in captured.out

def test_uptime(capsys):
    SystemManager.uptime()
    captured = capsys.readouterr()
    assert "System Uptime" in captured.out

def test_cpu_info(capsys):
    SystemManager.cpu_info()
    captured = capsys.readouterr()
    assert "CPU Information" in captured.out

def test_mem_info(capsys):
    SystemManager.mem_info()
    captured = capsys.readouterr()
    assert "Memory Usage" in captured.out

def test_os_detail(capsys):
    SystemManager.os_detail()
    captured = capsys.readouterr()
    assert "OS System" in captured.out

def test_file_size(capsys, tmp_path):
    # Create a dummy file
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello World")
    SystemManager.file_size(str(tmp_path))
    captured = capsys.readouterr()
    assert "Total Size" in captured.out
    assert "11 B" in captured.out

def test_file_recent(capsys, tmp_path):
    test_file = tmp_path / "recent.txt"
    test_file.touch()
    SystemManager.file_recent(str(tmp_path), count=1)
    captured = capsys.readouterr()
    assert "Recently Modified Files" in captured.out
    # Check for a fragment that is unlikely to be truncated
    assert "test_file_re" in captured.out
