# tests/output_to_clipboard_test.py
import sys
import os
import runpy
import subprocess
import importlib.util
import types
# import builtins # Not needed for rich.console.Console.input patching
import pytest
from pathlib import Path
from unittest import mock

# --- Path to the script under test ---
PYSCRIPTS_DIR = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PYSCRIPTS_DIR / "output_to_clipboard.py"

if not SCRIPT_PATH.is_file():
    pytest.fail(f"Test setup failed: SCRIPT_PATH not found: {SCRIPT_PATH}", pytrace=False)

# --- Global variable for clipboard ---
LAST_CLIP = None

# --- Mocks (Clipboard and HistoryUtils) ---
# This fixture will manage the clipboard mock for the loaded otc_module and sys.modules
@pytest.fixture(autouse=True)
def manage_clipboard_mock(monkeypatch):
    global LAST_CLIP
    LAST_CLIP = None # Reset for each test

    # This function will be patched into otc_module and sys.modules
    def new_fake_set_clipboard(text):
        global LAST_CLIP
        LAST_CLIP = text

    # Patch directly into the already loaded otc_module (for direct function calls)
    # This ensures otc_module.set_clipboard uses this version of new_fake_set_clipboard
    # which closes over the LAST_CLIP reset in this fixture invocation.
    monkeypatch.setattr(otc_module, 'set_clipboard', new_fake_set_clipboard, raising=False)

    # For completeness, also ensure sys.modules reflects this (for runpy executions)
    # Create a mock clipboard_utils module if it doesn't exist in sys.modules yet
    # (though it should due to script's own import guard)
    mock_clipboard_utils_name = 'cross_platform.clipboard_utils'
    if mock_clipboard_utils_name not in sys.modules:
        # This case should ideally not be hit if script has import guards,
        # but defensive programming for tests.
        cl_mod = types.ModuleType(mock_clipboard_utils_name)
        sys.modules[mock_clipboard_utils_name] = cl_mod
        # Ensure cross_platform parent package exists
        if 'cross_platform' not in sys.modules:
             sys.modules['cross_platform'] = types.ModuleType('cross_platform')
        setattr(sys.modules['cross_platform'], 'clipboard_utils', cl_mod)


    # Now patch set_clipboard on the (potentially newly created) module in sys.modules
    monkeypatch.setattr(sys.modules[mock_clipboard_utils_name], 'set_clipboard', new_fake_set_clipboard, raising=False)


MOCKED_HISTORY_COMMANDS = []
class FakeHistoryUtils:
    def __init__(self): self.shell_type = "mocked_shell"
    def get_nth_recent_command(self, n: int):
        global MOCKED_HISTORY_COMMANDS
        # Guard against MOCKED_HISTORY_COMMANDS being uninitialized if a test doesn't set it
        if MOCKED_HISTORY_COMMANDS is None: return None 
        return MOCKED_HISTORY_COMMANDS[n-1] if 0 < n <= len(MOCKED_HISTORY_COMMANDS) else None

@pytest.fixture
def mock_history_utils(monkeypatch):
    global MOCKED_HISTORY_COMMANDS; MOCKED_HISTORY_COMMANDS = []
    
    history_utils_mod_name = 'cross_platform.history_utils'
    # Ensure cross_platform parent package exists in sys.modules
    cross_pkg_name = 'cross_platform'
    if cross_pkg_name not in sys.modules:
        sys.modules[cross_pkg_name] = types.ModuleType(cross_pkg_name)
        
    history_utils_mod = types.ModuleType(history_utils_mod_name)
    history_utils_mod.HistoryUtils = FakeHistoryUtils
    
    monkeypatch.setitem(sys.modules, history_utils_mod_name, history_utils_mod)
    monkeypatch.setattr(sys.modules[cross_pkg_name], 'history_utils', history_utils_mod, raising=False)
    
    # Also patch it directly onto the otc_module if it has already imported it
    # (though script imports HistoryUtils inside a function, so sys.modules patching is key)
    if hasattr(otc_module, 'HistoryUtils'):
        monkeypatch.setattr(otc_module, 'HistoryUtils', FakeHistoryUtils, raising=False)
    
    return FakeHistoryUtils


# --- Load the script under test ---
try:
    # Ensure cross_platform.clipboard_utils is pre-mocked before otc_module imports it
    # This is implicitly handled by manage_clipboard_mock if it runs early enough,
    # but explicit pre-population for clarity during module load can be safer.
    _mock_cl_utils_name = 'cross_platform.clipboard_utils'
    if _mock_cl_utils_name not in sys.modules:
        _cl_mod_temp = types.ModuleType(_mock_cl_utils_name)
        _cl_mod_temp.set_clipboard = lambda x: None # Placeholder
        sys.modules[_mock_cl_utils_name] = _cl_mod_temp
        if 'cross_platform' not in sys.modules:
             sys.modules['cross_platform'] = types.ModuleType('cross_platform')
        setattr(sys.modules['cross_platform'], 'clipboard_utils', _cl_mod_temp)


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

# --- Test Helper ---
def run_otc_script_with_argv(argv_list, monkeypatch):
    # `runpy` executes the script in a new module context. Mocks need to be in `sys.modules`
    # or on builtin/global classes like rich.console.Console.
    monkeypatch.setattr(sys, "argv", argv_list)
    # The manage_clipboard_mock and mock_history_utils should ensure sys.modules are patched
    # before runpy executes the script.
    # mock_rich_console_input patches rich.console.Console.input which is global.
    runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

@pytest.fixture
def mock_rich_console_input(monkeypatch):
    mock_input_method = mock.Mock()
    # Patch rich.console.Console.input globally so instances created by runpy-executed script get it.
    monkeypatch.setattr("rich.console.Console.input", mock_input_method)
    return mock_input_method

# --- Tests ---
# Ensure manage_clipboard_mock (autouse) has run and patched otc_module.set_clipboard
def test_direct_command_execution_success(monkeypatch, capsys, mock_rich_console_input): # mock_rich_console_input not used but good practice if it were
    class FakeResult: stdout = "direct_out\n"; stderr = ""; returncode = 0
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: FakeResult())
    
    # This call uses the otc_module.set_clipboard, which should be patched by manage_clipboard_mock
    _op_ok, _user_cancel, _has_err, exit_c = otc_module.run_command_and_copy_main(
        command_parts=['echo', 'direct_hello'], replay_nth=None, no_stats=True
    )
    assert exit_c == 0
    
    out_cap, err_cap = capsys.readouterr()
    assert "Copied command output to clipboard." in out_cap
    assert LAST_CLIP == "direct_out" # Check the global updated by the mock
    assert err_cap == "" # No error messages expected

def test_direct_command_execution_failure(monkeypatch, capsys, mock_rich_console_input):
    class FakeResult: stdout = ""; stderr = "direct_err_msg"; returncode = 1
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: FakeResult())

    _op_ok, _user_cancel, _has_err, exit_c = otc_module.run_command_and_copy_main(
        command_parts=['cmd_direct_fail'], replay_nth=None, no_stats=True
    )
    # Script itself exits 0, but prints a warning for command failure.
    # If output (even if error output) is copied, script considers its primary job done.
    assert exit_c == 0 

    out_cap, err_cap = capsys.readouterr()
    assert "Copied command output to clipboard." in out_cap 
    assert "Command 'cmd_direct_fail' exited with status 1" in err_cap
    assert LAST_CLIP == "direct_err_msg"

def test_replay_invalid_N_negative(monkeypatch, capsys, mock_history_utils):
    with pytest.raises(SystemExit) as e:
        # This uses runpy, so sys.modules patching for clipboard/history is key.
        # Rich input patching is also key for runpy.
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
    global MOCKED_HISTORY_COMMANDS; MOCKED_HISTORY_COMMANDS = ["baz", "bar", "foo"] # History: foo (N=3), bar (N=2), baz (N=1)
    mock_rich_console_input.return_value = 'y' # Mock user confirmation
    
    def fake_subprocess_run(cmd_str, shell, capture_output, text, check):
        assert cmd_str == "bar" # N=2 from MOCKED_HISTORY_COMMANDS
        return types.SimpleNamespace(stdout="val_from_bar\n", stderr="", returncode=0)
    monkeypatch.setattr(subprocess, 'run', fake_subprocess_run)
    
    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '-r', '2', '--no-stats'], monkeypatch)
    assert e.value.code == 0 # Expect script success

    out_cap, err_cap = capsys.readouterr()
    # Check log messages (stderr for Rich info/prompts)
    assert "Attempting to replay history entry N=2" in err_cap
    assert "Found history command: 'bar'" in err_cap
    assert "User approved. Re-running: bar" in err_cap
    # Check actual output (stdout for Rich success messages)
    assert "Copied command output to clipboard." in out_cap
    assert LAST_CLIP == "val_from_bar" # Check clipboard content

def test_replay_default_N_no_args_success(monkeypatch, capsys, mock_history_utils, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS; MOCKED_HISTORY_COMMANDS = ["echo hello default", "ls -la"] # Default N=1 is "echo hello default"
    mock_rich_console_input.return_value = 'y'
    monkeypatch.setattr(subprocess, 'run', 
                        lambda cmd_str, **kwargs: types.SimpleNamespace(stdout="output from echo default\n", stderr="", returncode=0) 
                        if cmd_str == "echo hello default" else pytest.fail(f"Unexpected command: {cmd_str}"))
    
    with pytest.raises(SystemExit) as e:
        # No command, no -r => defaults to -r 1
        run_otc_script_with_argv([str(SCRIPT_PATH), '--no-stats'], monkeypatch) 
    assert e.value.code == 0

    out_cap, err_cap = capsys.readouterr()
    assert "Attempting to replay history entry N=1" in err_cap
    assert "Found history command: 'echo hello default'" in err_cap
    assert "Copied command output to clipboard." in out_cap
    assert LAST_CLIP == "output from echo default"

@pytest.mark.parametrize("problematic_command_in_history", [
    f"{SCRIPT_PATH.name} -r 2", f"python {SCRIPT_PATH.name} --other-arg", f"./{SCRIPT_PATH.name}",
    f"bash {SCRIPT_PATH.name} run", f"{SCRIPT_PATH.stem} -r 1", f"python {SCRIPT_PATH.stem} --arg"
])
def test_replay_loop_prevention(monkeypatch, capsys, mock_history_utils, problematic_command_in_history, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS; MOCKED_HISTORY_COMMANDS = [problematic_command_in_history, "other"]
    # mock_rich_console_input is patched globally, but input should not be prompted due to loop detection.
    # If it were prompted, mock_rich_console_input.side_effect would make it fail.
    mock_rich_console_input.side_effect = lambda prompt: pytest.fail("Input should not be prompted due to loop detection.")
    
    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '-r', '1', '--no-stats'], monkeypatch)
    assert e.value.code == 1 # Script exits with error on loop detection
    _out, err = capsys.readouterr()
    normalized_err = " ".join(err.split()) 
    assert "Loop detected" in normalized_err 
    # The exact command string from history should be in the error message
    assert problematic_command_in_history in err # Check raw error message for the command string
    assert "is this script. Aborting." in normalized_err

def test_replay_ignored_if_command_provided(monkeypatch, capsys, mock_history_utils, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS; MOCKED_HISTORY_COMMANDS = ["history_cmd"] # Should be ignored
    
    # Mock subprocess.run to check that the explicit command is run, not history_cmd
    # The lambda now needs to match the full signature of subprocess.run if strict
    def fake_run(cmd_parts_list_or_str, shell, capture_output, text, check):
        # Command in script is " ".join(command_parts) if command_parts, so it's a string
        assert "echo test command" in cmd_parts_list_or_str
        return types.SimpleNamespace(stdout="hello_explicit\n", stderr="", returncode=0)
    monkeypatch.setattr(subprocess, 'run', fake_run)
    
    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '-r', '1', '--no-stats', '--', 'echo', 'test', 'command'], monkeypatch)
    assert e.value.code == 0

    out_cap, err_cap = capsys.readouterr()
    assert "Copied command output to clipboard." in out_cap
    assert LAST_CLIP == "hello_explicit"
    # Verify that history replay was not attempted
    assert "Attempting to replay history entry N=" not in err_cap
    assert "Both command and --replay-history specified" in err_cap # Info message

def test_replay_history_command_not_found(monkeypatch, capsys, mock_history_utils, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS; MOCKED_HISTORY_COMMANDS = ["one cmd"] # Only one command in history
    
    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '-r', '2', '--no-stats'], monkeypatch) # Ask for 2nd
    assert e.value.code == 1 # Error exit
    _out, err = capsys.readouterr()
    assert "Failed to retrieve the 2nd command from history." in err

def test_replay_user_cancel_N_input(monkeypatch, capsys, mock_history_utils, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS; MOCKED_HISTORY_COMMANDS = ["cmd_to_cancel_N"]
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail("subprocess.run should not be called if user cancels"))
    mock_rich_console_input.return_value = 'n' # User says no
    
    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '-r', '1', '--no-stats'], monkeypatch)
    assert e.value.code == 0 # Clean exit on user cancel
    
    _out_cap, err_cap = capsys.readouterr() 
    assert "User cancelled re-run." in err_cap
    assert LAST_CLIP is None # Clipboard should not be set

def test_replay_user_cancel_default_input(monkeypatch, capsys, mock_history_utils, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS; MOCKED_HISTORY_COMMANDS = ["cmd_to_cancel_def"]
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail("subprocess.run should not be called"))
    mock_rich_console_input.return_value = 'n' # User says no

    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '--no-stats'], monkeypatch) # Default -r 1
    assert e.value.code == 0 # Clean exit
    
    _out, err = capsys.readouterr()
    assert "User cancelled re-run." in err
    assert LAST_CLIP is None

def test_replay_eof_error_on_input(monkeypatch, capsys, mock_history_utils, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS; MOCKED_HISTORY_COMMANDS = ["cmd_eof"]
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail("subprocess.run should not be called"))
    mock_rich_console_input.side_effect = EOFError # Simulate EOF on input

    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '-r', '1', '--no-stats'], monkeypatch)
    assert e.value.code == 0 # Clean exit, assumes 'No'
    
    _out, err = capsys.readouterr()
    # Script behavior for EOFError on rich.input might be different than builtins.input
    # The script currently catches EOFError and prints a specific message.
    assert "No input for confirmation (EOFError). Assuming 'No'." in err # Check for specific message
    assert "User cancelled re-run." in err # Consequence of assuming 'No'
    assert LAST_CLIP is None
