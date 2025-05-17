# tests/test_output_to_clipboard.py
import sys
import os
import runpy
import subprocess
import importlib.util
import types
import builtins
import pytest

# Path to the script under test
SCRIPT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'output_to_clipboard.py')
)

# Global variable to capture clipboard contents in tests
LAST_CLIP = None

@pytest.fixture(autouse=True)
def dummy_clipboard_module(monkeypatch):
    """
    Autouse fixture to stub out cross_platform.clipboard_utils.set_clipboard
    and capture its input to LAST_CLIP.
    """
    global LAST_CLIP
    LAST_CLIP = None
    clipboard_mod = types.ModuleType('cross_platform.clipboard_utils')
    def fake_set_clipboard(text):
        global LAST_CLIP
        LAST_CLIP = text
    clipboard_mod.set_clipboard = fake_set_clipboard
    cross_pkg = types.ModuleType('cross_platform')
    cross_pkg.clipboard_utils = clipboard_mod
    monkeypatch.setitem(sys.modules, 'cross_platform', cross_pkg)
    monkeypatch.setitem(sys.modules, 'cross_platform.clipboard_utils', clipboard_mod)

def test_run_command_and_copy_success(monkeypatch, capsys):
    # Simulate a successful subprocess.run
    class FakeResult:
        stdout = "out\n"
        stderr = ""
        returncode = 0
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: FakeResult())
    spec = importlib.util.spec_from_file_location("otc", SCRIPT_PATH)
    otc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(otc)
    otc.run_command_and_copy(['echo', 'hello'])
    out, err = capsys.readouterr()
    assert "Copied command output to clipboard." in out
    assert LAST_CLIP == "out"
    assert err == ""

def test_run_command_and_copy_failure(monkeypatch, capsys):
    # Simulate a failing subprocess.run
    class FakeResult:
        stdout = ""
        stderr = "err"
        returncode = 1
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: FakeResult())
    spec = importlib.util.spec_from_file_location("otc", SCRIPT_PATH)
    otc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(otc)
    otc.run_command_and_copy(['cmd'])
    out, err = capsys.readouterr()
    assert "Copied command output to clipboard." in out
    assert "Warning: Command 'cmd' exited with status 1" in err
    assert LAST_CLIP == "err"

def test_invalid_replay_history(monkeypatch):
    # Test that -r 0 triggers an error
    monkeypatch.setitem(os.environ, 'SHELL', '/bin/bash')
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: types.SimpleNamespace(stdout="", stderr="", returncode=1))
    clipboard_mod = types.ModuleType('cross_platform.clipboard_utils')
    clipboard_mod.set_clipboard = lambda x: None
    cross_pkg = types.ModuleType('cross_platform')
    cross_pkg.clipboard_utils = clipboard_mod
    monkeypatch.setitem(sys.modules, 'cross_platform', cross_pkg)
    monkeypatch.setitem(sys.modules, 'cross_platform.clipboard_utils', clipboard_mod)
    monkeypatch.setattr(sys, 'argv', ['output_to_clipboard.py', '-r', '0'])
    with pytest.raises(SystemExit) as e:
        runpy.run_path(SCRIPT_PATH, run_name="__main__")
    assert e.value.code == 1

def test_replay_history_branch_explicit_N(monkeypatch, capsys):
    # Test replay-history N works (N=2)
    monkeypatch.setitem(os.environ, 'SHELL', '/bin/bash')
    def fake_run(cmd, *args, **kwargs):
        if isinstance(cmd, list):
            return types.SimpleNamespace(stdout="1  foo\n2  bar\n3  baz\n", stderr="", returncode=0)
        return types.SimpleNamespace(stdout="val\n", stderr="", returncode=0)
    monkeypatch.setattr(subprocess, 'run', fake_run)
    monkeypatch.setattr(builtins, 'input', lambda prompt: 'y')
    monkeypatch.setattr(sys, 'argv', ['output_to_clipboard.py', '-r', '2'])
    runpy.run_path(SCRIPT_PATH, run_name="__main__")
    out, err = capsys.readouterr()
    assert "[INFO] Replaying history entry N=2..." in err
    assert "Copied command output to clipboard." in out
    assert LAST_CLIP == "val"

def test_history_branch_success(monkeypatch, capsys):
    # Test default history branch (N=1)
    monkeypatch.setitem(os.environ, 'SHELL', '/bin/bash')
    
    def fake_run(cmd, *args, **kwargs):
        # Simulate history output with 'echo hello' as most recent
        if isinstance(cmd, list):
            return types.SimpleNamespace(stdout="1  ls -la\n2  echo hello\n", stderr="", returncode=0)
        return types.SimpleNamespace(stdout="output from echo\n", stderr="", returncode=0)
    
    monkeypatch.setattr(subprocess, 'run', fake_run)
    monkeypatch.setattr(builtins, 'input', lambda prompt: 'y')
    monkeypatch.setattr(sys, 'argv', ['output_to_clipboard.py'])

    runpy.run_path(SCRIPT_PATH, run_name="__main__")
    out, err = capsys.readouterr()

    # Confirm expected stderr and stdout messages
    assert "[INFO] Replaying history entry N=1..." in err
    assert "User approved. Re-running: echo hello" in err
    assert "Copied command output to clipboard." in out
    assert LAST_CLIP == "output from echo"
def test_history_loop_prevention(monkeypatch, capsys):
    # Test that invoking the script from history is prevented
    monkeypatch.setitem(os.environ, 'SHELL', '/bin/bash')
    def fake_run(cmd, *args, **kwargs):
        return types.SimpleNamespace(stdout="1  output_to_clipboard.py arg\n", stderr="", returncode=0)
    monkeypatch.setattr(subprocess, 'run', fake_run)
    monkeypatch.setattr(builtins, 'input', lambda prompt: 'y')
    monkeypatch.setattr(sys, 'argv', ['output_to_clipboard.py'])
    with pytest.raises(SystemExit) as e:
        runpy.run_path(SCRIPT_PATH, run_name="__main__")
    assert e.value.code == 1

def test_replay_history_ignored(monkeypatch, capsys):
    # Test that -r is ignored when an explicit command follows
    monkeypatch.setitem(os.environ, 'SHELL', '/bin/bash')
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: types.SimpleNamespace(stdout="hello\n", stderr="", returncode=0))
    monkeypatch.setattr(sys, 'argv', ['output_to_clipboard.py', '-r', '2', 'echo', 'test'])
    runpy.run_path(SCRIPT_PATH, run_name="__main__")
    out, err = capsys.readouterr()
    assert "Copied command output to clipboard." in out
    assert LAST_CLIP == "hello"

def test_unsupported_shell_warning(monkeypatch, capsys):
    # Test warning for unsupported shells
    monkeypatch.setitem(os.environ, 'SHELL', '/bin/fish')
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: types.SimpleNamespace(stdout="", stderr="error", returncode=1))
    monkeypatch.setattr(sys, 'argv', ['output_to_clipboard.py'])
    with pytest.raises(SystemExit):
        runpy.run_path(SCRIPT_PATH, run_name="__main__")
    out, err = capsys.readouterr()
    assert "[ERROR] Failed to retrieve history" in err
