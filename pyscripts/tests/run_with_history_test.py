# tests/run_with_history_test.py
import os
import sys
import subprocess
import tempfile
from pathlib import Path
import pytest

import run_with_history
from cross_platform.history_utils import HistoryUtils

@pytest.fixture(autouse=True)
def temp_history_file(monkeypatch, tmp_path):
    # Force shell_type to bash to avoid Zsh warnings in most tests
    monkeypatch.setattr(HistoryUtils, '__init__', lambda self: setattr(self, 'shell_type', 'bash'))
    # Create a fake history file with a mix of commands and paths
    hist = tmp_path / "fake_history"
    lines = [
        "ls /tmp",
        "cd /var/log",
        "echo hello",
        "vim /etc/hosts",
        "pytest tests/sample_test.py",
        "cd /home/user/project",
        "rwc /home/user/project/file.txt",
    ]
    hist.write_text("\n".join(lines))
    # Monkey-patch HistoryUtils to use this fake history file
    monkeypatch.setattr(HistoryUtils, '_get_history_file_path', lambda self: str(hist))
    # Treat all absolute paths as existing for the purpose of tests
    orig_exists = Path.exists
    def fake_exists(self):
        if self.is_absolute():
            return True
        return orig_exists(self)
    monkeypatch.setattr(Path, 'exists', fake_exists)
    return hist

def run_main(capsys, *args):
    # Temporarily override sys.argv and capture exit code/output
    old_argv = sys.argv[:]
    sys.argv = ['run_with_history.py'] + list(args)
    try:
        with pytest.raises(SystemExit) as excinfo:
            run_with_history.main()
        out, err = capsys.readouterr()
        return excinfo.value.code, out, err
    finally:
        sys.argv = old_argv

def test_list_recent_paths(capsys):
    code, out, err = run_main(capsys)
    assert code == 0
    lines = out.strip().splitlines()
    # Most recent path should be the file
    assert lines[0].startswith("1: /home/user/project/file.txt")
    # Next should be its parent directory
    assert any("/home/user/project" in line for line in lines[1:])
    # /etc/hosts should appear somewhere
    assert any("/etc/hosts" in line for line in lines)
    # No stderr output
    assert err == ""

def test_run_command_default(monkeypatch, tmp_path, capsys):
    # Stub subprocess.run to capture its arguments instead of executing
    called = {}
    def fake_run(cmd, **kwargs):
        called['cmd'] = cmd
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(run_with_history, 'subprocess', type('m', (), {'run': fake_run}))

    code, out, err = run_main(capsys, 'dummy.sh')
    assert code == 0
    # Ensure we passed the most recent path to the command
    assert called['cmd'] == ['dummy.sh', '/home/user/project/file.txt']
    assert out == ''
    assert err == ''

def test_invalid_index(capsys):
    code, out, err = run_main(capsys, '-n', '10', 'dummy')
    assert code == 1
    assert "Error: Cannot retrieve path #10" in err

def test_zsh_warning(monkeypatch, capsys):
    # Simulate zsh environment without all required options
    monkeypatch.setattr(HistoryUtils, '__init__', lambda self: setattr(self, 'shell_type', 'zsh'))
    # Fake subprocess.run for 'zsh -lic setopt'
    def fake_run(cmd, capture_output, text):
        class R:
            stdout = "share_history inc_append_history"
        return R()
    monkeypatch.setattr(subprocess, 'run', fake_run)

    code, out, err = run_main(capsys)
    assert code == 0
    assert "Warning: Zsh options not set: inc_append_history_time" in err
    # Do not require listing paths here (covered by other tests)
