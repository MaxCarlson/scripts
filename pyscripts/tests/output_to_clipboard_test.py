# File: tests/output_to_clipboard_test.py
from __future__ import annotations

import sys
import os
import runpy
import subprocess
import importlib.util
import types
import shutil
import pytest
from pathlib import Path
from unittest import mock

# --- Path to the script under test ---
PYSCRIPTS_DIR = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PYSCRIPTS_DIR / "output_to_clipboard.py"

if not SCRIPT_PATH.is_file():
    pytest.fail(f"Test setup failed: SCRIPT_PATH not found: {SCRIPT_PATH}", pytrace=False)

# --- Global variable for clipboard ---
LAST_CLIP = ""

# --- Mocks (Clipboard and HistoryUtils) ---
def _ensure_cross_platform_package():
    """Ensures 'cross_platform' is a package in sys.modules for sub-module mocking."""
    if 'cross_platform' not in sys.modules:
        cross_platform_pkg = types.ModuleType('cross_platform')
        cross_platform_pkg.__path__ = [str(PYSCRIPTS_DIR / 'cross_platform')]  # mark as package
        sys.modules['cross_platform'] = cross_platform_pkg
    elif not hasattr(sys.modules['cross_platform'], '__path__'):
        sys.modules['cross_platform'].__path__ = [str(PYSCRIPTS_DIR / 'cross_platform')]


# Reference to the loaded module, needed for patching. Initialized after module load.
otc_module = None

@pytest.fixture(autouse=True)
def manage_clipboard_mock(monkeypatch):
    """Provide set_clipboard/get_clipboard that operate on LAST_CLIP."""
    global LAST_CLIP
    LAST_CLIP = ""  # Reset for each test

    _ensure_cross_platform_package()

    mock_clipboard_utils_name = 'cross_platform.clipboard_utils'
    mock_clipboard_utils_mod = types.ModuleType(mock_clipboard_utils_name)

    def _set(text):
        global LAST_CLIP
        LAST_CLIP = text

    def _get():
        return LAST_CLIP

    mock_clipboard_utils_mod.set_clipboard = _set
    mock_clipboard_utils_mod.get_clipboard = _get

    # Install into sys.modules
    monkeypatch.setitem(sys.modules, mock_clipboard_utils_name, mock_clipboard_utils_mod)
    # Also attach onto the parent package
    

    # Patch directly onto the already-loaded otc_module (if any)
    if otc_module:
        monkeypatch.setattr(otc_module, 'set_clipboard', _set, raising=False)
        monkeypatch.setattr(otc_module, 'get_clipboard', _get, raising=False)


MOCKED_HISTORY_COMMANDS = []

class FakeHistoryUtils:
    def __init__(self):
        self.shell_type = "mocked_shell"
    def get_nth_recent_command(self, n: int):
        global MOCKED_HISTORY_COMMANDS
        if MOCKED_HISTORY_COMMANDS is None:
            return None
        return MOCKED_HISTORY_COMMANDS[n-1] if 0 < n <= len(MOCKED_HISTORY_COMMANDS) else None


@pytest.fixture
def mock_history_utils(monkeypatch):
    global MOCKED_HISTORY_COMMANDS
    MOCKED_HISTORY_COMMANDS = []  # Reset for each test

    _ensure_cross_platform_package()

    history_utils_mod_name = 'cross_platform.history_utils'
    mock_history_utils_mod = types.ModuleType(history_utils_mod_name)
    mock_history_utils_mod.HistoryUtils = FakeHistoryUtils

    monkeypatch.setitem(sys.modules, history_utils_mod_name, mock_history_utils_mod)
    

    if otc_module:
        monkeypatch.setattr(otc_module, 'HistoryUtils', FakeHistoryUtils, raising=False)

    return FakeHistoryUtils


# --- Load the script under test (ensure mocks exist first) ---
try:
    _ensure_cross_platform_package()

    # Pre-seed minimal mocks before importing script
    cl_name = 'cross_platform.clipboard_utils'
    if cl_name not in sys.modules:
        _cl = types.ModuleType(cl_name)
        _cl.set_clipboard = lambda x: None
        _cl.get_clipboard = lambda: ""
        sys.modules[cl_name] = _cl
        setattr(sys.modules['cross_platform'], 'clipboard_utils', _cl)

    hist_name = 'cross_platform.history_utils'
    if hist_name not in sys.modules:
        _hist = types.ModuleType(hist_name)
        _hist.HistoryUtils = lambda: None
        sys.modules[hist_name] = _hist
        setattr(sys.modules['cross_platform'], 'history_utils', _hist)

    otc_module_spec = importlib.util.spec_from_file_location("otc_module", str(SCRIPT_PATH))
    if otc_module_spec is None or otc_module_spec.loader is None:
        raise ImportError(f"Could not create module spec for {SCRIPT_PATH}")

    otc_module = importlib.util.module_from_spec(otc_module_spec)
    sys.modules['otc_module'] = otc_module
    otc_module_spec.loader.exec_module(otc_module)

except FileNotFoundError as e_fnf:
    pytest.fail(f"Importlib setup failed (FileNotFoundError): {e_fnf}\nSCRIPT_PATH was: {SCRIPT_PATH}", pytrace=False)
except Exception as e_imp:
    pytest.fail(f"Unexpected error during importlib setup: {e_imp}\nSCRIPT_PATH was: {SCRIPT_PATH}", pytrace=False)


# --- Test Helpers ---
def run_otc_script_with_argv(argv_list, monkeypatch):
    monkeypatch.setattr(sys, "argv", argv_list)
    runpy.run_path(str(SCRIPT_PATH), run_name="__main__")


@pytest.fixture
def mock_rich_console_input(monkeypatch):
    mock_input_method = mock.Mock()
    monkeypatch.setattr("rich.console.Console.input", mock_input_method)
    return mock_input_method


# ----------------------------
# Tests (direct execution)
# ----------------------------

def test_direct_command_execution_success(monkeypatch, capsys, mock_rich_console_input):
    class FakeResult:
        stdout = "direct_out\n"
        stderr = ""
        returncode = 0
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: FakeResult())

    _op_ok, _user_cancel, _has_err, exit_c = otc_module.run_command_and_copy_main(
        command_parts=['echo', 'direct_hello'], replay_nth=None, no_stats=True, wrap=False
    )
    assert exit_c == 0

    out_cap, err_cap = capsys.readouterr()
    assert "Copied command output to clipboard." in out_cap
    assert LAST_CLIP == "direct_out"
    assert err_cap == ""  # No stats


def test_direct_command_execution_failure(monkeypatch, capsys, mock_rich_console_input):
    class FakeResult:
        stdout = ""
        stderr = "direct_err_msg"
        returncode = 1
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: FakeResult())

    _op_ok, _user_cancel, _has_err, exit_c = otc_module.run_command_and_copy_main(
        command_parts=['cmd_direct_fail'], replay_nth=None, no_stats=True, wrap=False
    )
    assert exit_c == 0

    out_cap, err_cap = capsys.readouterr()
    assert "Copied command output to clipboard." in out_cap
    assert "Command 'cmd_direct_fail' exited with status 1" in err_cap
    assert LAST_CLIP == "direct_err_msg"
    assert err_cap.strip().startswith("[WARNING]")  # Warning present, no stats


# ----------------------------
# Wrap mode
# ----------------------------

def test_direct_command_execution_with_wrap(monkeypatch, capsys):
    command_str = "ls -l"
    fake_output = "total 0\n-rw-r--r-- 1 user user 0 Jun 21 10:00 file.txt"
    class FakeResult:
        stdout = fake_output + "\n"
        stderr = ""
        returncode = 0
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: FakeResult())

    _op_ok, _user_cancel, _has_err, exit_c = otc_module.run_command_and_copy_main(
        command_parts=[command_str], replay_nth=None, no_stats=False, wrap=True
    )
    assert exit_c == 0
    out_cap, err_cap = capsys.readouterr()
    assert "Copied command output to clipboard." in out_cap

    expected_clipboard = f"$ {command_str}\n```\n{fake_output}\n```"
    assert LAST_CLIP == expected_clipboard
    assert "Wrapping Mode" in err_cap
    assert "Wrapped (command + code block)" in err_cap


def test_replay_history_with_wrap(monkeypatch, capsys, mock_history_utils, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS
    MOCKED_HISTORY_COMMANDS = ["my_command_history", "another_cmd"]
    mock_rich_console_input.return_value = 'y'

    command_from_history = "my_command_history"
    fake_output = "History command output here"

    def fake_subprocess_run(cmd_str, shell, capture_output, text, check):
        # Ensure our original command is used inside the wrapper
        assert command_from_history in cmd_str
        return types.SimpleNamespace(stdout=fake_output + "\n", stderr="", returncode=0)

    monkeypatch.setattr(subprocess, 'run', fake_subprocess_run)

    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '-r', '1', '-w'], monkeypatch)
    assert e.value.code == 0

    out_cap, err_cap = capsys.readouterr()
    assert "Copied command output to clipboard." in out_cap
    expected_clipboard = f"$ {command_from_history}\n```\n{fake_output}\n```"
    assert LAST_CLIP == expected_clipboard
    assert "Wrapping Mode" in err_cap
    assert "Wrapped (command + code block)" in err_cap


# ----------------------------
# Replay edge cases
# ----------------------------

def test_replay_invalid_N_negative(monkeypatch, capsys, mock_history_utils):
    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '-r', '-1', '--no-stats'], monkeypatch)
    assert e.value.code == 1
    _out, err = capsys.readouterr()
    assert "Value for --replay-history (-r) must be positive." in err


def test_replay_invalid_N_zero(monkeypatch, capsys, mock_history_utils):
    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '-r', '0', '--no-stats'], monkeypatch)
    assert e.value.code == 1
    _out, err = capsys.readouterr()
    assert "Value for --replay-history (-r) must be positive." in err


def test_replay_history_explicit_N_success(monkeypatch, capsys, mock_history_utils, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS
    MOCKED_HISTORY_COMMANDS = ["baz", "bar", "foo"]
    mock_rich_console_input.return_value = 'y'

    def fake_subprocess_run(cmd_str, shell, capture_output, text, check):
        assert "bar" in cmd_str
        return types.SimpleNamespace(stdout="val_from_bar\n", stderr="", returncode=0)

    monkeypatch.setattr(subprocess, 'run', fake_subprocess_run)

    _op_ok, _user_cancel, _has_err, exit_c = otc_module.run_command_and_copy_main(
        command_parts=None, replay_nth=2, no_stats=True, wrap=False
    )
    assert exit_c == 0

    out_cap, err_cap = capsys.readouterr()
    assert "Attempting to replay history entry N=2" in err_cap
    assert "Found history command: 'bar'" in err_cap
    assert "User approved. Re-running: bar" in err_cap
    assert "Copied command output to clipboard." in out_cap
    assert LAST_CLIP == "val_from_bar"
    assert err_cap.strip().startswith("[INFO]")


def test_replay_default_N_no_args_success(monkeypatch, capsys, mock_history_utils, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS
    MOCKED_HISTORY_COMMANDS = ["echo hello default", "ls -la"]
    mock_rich_console_input.return_value = 'y'

    def _fake_run(cmd_str, **kwargs):
        assert "echo hello default" in cmd_str
        return types.SimpleNamespace(stdout="output from echo default\n", stderr="", returncode=0)

    monkeypatch.setattr(subprocess, 'run', _fake_run)

    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '--no-stats'], monkeypatch)
    assert e.value.code == 0

    out_cap, err_cap = capsys.readouterr()
    assert "Attempting to replay history entry N=1" in err_cap
    assert "Found history command: 'echo hello default'" in err_cap
    assert "Copied command output to clipboard." in out_cap
    assert LAST_CLIP == "output from echo default"
    assert err_cap.strip().startswith("[INFO]")


@pytest.mark.parametrize(
    "problematic_command_in_history",
    [
        f"{SCRIPT_PATH.name} -r 2",
        f"python {SCRIPT_PATH.name} --other-arg",
        f"./{SCRIPT_PATH.name}",
        f"bash {SCRIPT_PATH.name} run",
        f"{SCRIPT_PATH.stem} -r 1",
        f"python {SCRIPT_PATH.stem} --arg",
    ],
)
def test_replay_loop_prevention(monkeypatch, capsys, mock_history_utils, problematic_command_in_history, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS
    MOCKED_HISTORY_COMMANDS = [problematic_command_in_history, "other"]
    mock_rich_console_input.side_effect = lambda prompt: pytest.fail("Input should not be prompted due to loop detection.")

    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '-r', '1', '--no-stats'], monkeypatch)
    assert e.value.code == 1
    _out, err = capsys.readouterr()
    normalized_err = " ".join(err.split())
    assert "Loop detected" in normalized_err
    assert problematic_command_in_history in err
    assert "is this script. Aborting." in normalized_err


def test_replay_ignored_if_command_provided(monkeypatch, capsys, mock_history_utils, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS
    MOCKED_HISTORY_COMMANDS = ["history_cmd"]

    def fake_run(cmd_str, shell, capture_output, text, check):
        assert "echo test command" in cmd_str  # It should execute provided command, not history
        return types.SimpleNamespace(stdout="hello_explicit\n", stderr="", returncode=0)

    monkeypatch.setattr(subprocess, 'run', fake_run)

    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '-r', '1', '--no-stats', '--', 'echo', 'test', 'command'], monkeypatch)
    assert e.value.code == 0

    out_cap, err_cap = capsys.readouterr()
    assert "Copied command output to clipboard." in out_cap
    assert LAST_CLIP == "hello_explicit"
    assert "Attempting to replay history entry N=" not in err_cap
    assert "Both command and --replay-history specified" in err_cap


def test_replay_history_command_not_found(monkeypatch, capsys, mock_history_utils, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS
    MOCKED_HISTORY_COMMANDS = ["one cmd"]

    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '-r', '2', '--no-stats'], monkeypatch)
    assert e.value.code == 1
    _out, err = capsys.readouterr()
    assert "Failed to retrieve the 2nd command from history." in err


def test_replay_user_cancel_N_input(monkeypatch, capsys, mock_history_utils, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS
    MOCKED_HISTORY_COMMANDS = ["cmd_to_cancel_N"]
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail("subprocess.run should not be called if user cancels"))
    mock_rich_console_input.return_value = 'n'

    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '-r', '1', '--no-stats'], monkeypatch)
    assert e.value.code == 0

    _out_cap, err_cap = capsys.readouterr()
    assert "User cancelled re-run." in err_cap
    assert LAST_CLIP == ""


def test_replay_user_cancel_default_input(monkeypatch, capsys, mock_history_utils, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS
    MOCKED_HISTORY_COMMANDS = ["cmd_to_cancel_def"]
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail("subprocess.run should not be called"))
    mock_rich_console_input.return_value = 'n'

    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '--no-stats'], monkeypatch)
    assert e.value.code == 0

    _out, err = capsys.readouterr()
    assert "User cancelled re-run." in err
    assert LAST_CLIP == ""


def test_replay_eof_error_on_input(monkeypatch, capsys, mock_history_utils, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS
    MOCKED_HISTORY_COMMANDS = ["cmd_eof"]
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail("subprocess.run should not be called"))
    mock_rich_console_input.side_effect = EOFError

    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '-r', '1', '--no-stats'], monkeypatch)
    assert e.value.code == 0

    _out, err = capsys.readouterr()
    assert "No input for confirmation (EOFError). Assuming 'No'." in err
    assert "User cancelled re-run." in err
    assert LAST_CLIP == ""


# ----------------------------
# New: Append mode
# ----------------------------

def test_append_mode_appends_with_single_space(monkeypatch, capsys):
    # Seed clipboard
    global LAST_CLIP
    LAST_CLIP = "alpha"

    class FakeResult:
        stdout = "beta\n"
        stderr = ""
        returncode = 0
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: FakeResult())

    _op_ok, _user_cancel, _has_err, exit_c = otc_module.run_command_and_copy_main(
        command_parts=['echo', 'beta'], replay_nth=None, no_stats=True, wrap=False, append=True
    )
    assert exit_c == 0
    assert LAST_CLIP == "alpha beta"  # exactly one space


def test_append_mode_with_wrapped_output(monkeypatch, capsys):
    global LAST_CLIP
    LAST_CLIP = "start"

    class FakeResult:
        stdout = "X\nY\n"
        stderr = ""
        returncode = 0
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: FakeResult())

    _op_ok, _user_cancel, _has_err, exit_c = otc_module.run_command_and_copy_main(
        command_parts=['echo', 'foo'], replay_nth=None, no_stats=True, wrap=True, append=True
    )
    assert exit_c == 0
    assert LAST_CLIP.startswith("start $ echo foo\n```") or LAST_CLIP.startswith("start $ echo foo\r\n```")


# ----------------------------
# New: Alias/function support – wrapper building
# ----------------------------

def test_shell_wrapper_auto_zsh(monkeypatch):
    # Simulate zsh environment
    monkeypatch.setenv("SHELL", "/usr/bin/zsh")

    captured_cmd = {}
    def fake_run(cmd_str, shell, capture_output, text, check):
        captured_cmd["cmd"] = cmd_str
        return types.SimpleNamespace(stdout="ok\n", stderr="", returncode=0)

    monkeypatch.setattr(subprocess, 'run', fake_run)

    _op_ok, _user_cancel, _has_err, exit_c = otc_module.run_command_and_copy_main(
        command_parts=['gst'], replay_nth=None, no_stats=True, wrap=False
    )
    assert exit_c == 0
    # Ensure wrapper chose zsh -i -c and still contains original command
    assert captured_cmd["cmd"].startswith("zsh -i -c ")
    assert "gst" in captured_cmd["cmd"]


def test_shell_wrapper_auto_bash(monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/bash")

    captured_cmd = {}
    def fake_run(cmd_str, shell, capture_output, text, check):
        captured_cmd["cmd"] = cmd_str
        return types.SimpleNamespace(stdout="ok\n", stderr="", returncode=0)

    monkeypatch.setattr(subprocess, 'run', fake_run)

    _op_ok, _user_cancel, _has_err, exit_c = otc_module.run_command_and_copy_main(
        command_parts=['myalias'], replay_nth=None, no_stats=True, wrap=False
    )
    assert exit_c == 0
    assert captured_cmd["cmd"].startswith("bash -lc ")
    assert "myalias" in captured_cmd["cmd"]


def test_shell_wrapper_forced_shell_flag(monkeypatch):
    # Force fish via parameter; verify wrapper respects it even if env says bash.
    monkeypatch.setenv("SHELL", "/bin/bash")

    captured_cmd = {}
    def fake_run(cmd_str, shell, capture_output, text, check):
        captured_cmd["cmd"] = cmd_str
        return types.SimpleNamespace(stdout="ok\n", stderr="", returncode=0)

    monkeypatch.setattr(subprocess, 'run', fake_run)

    _op_ok, _user_cancel, _has_err, exit_c = otc_module.run_command_and_copy_main(
        command_parts=['abbr'], replay_nth=None, no_stats=True, wrap=False, append=False, shell_choice="fish"
    )
    assert exit_c == 0
    assert captured_cmd["cmd"].startswith("fish -i -c ")
    assert "abbr" in captured_cmd["cmd"]
