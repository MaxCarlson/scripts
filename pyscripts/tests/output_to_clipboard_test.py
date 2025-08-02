import sys
import os
import runpy
import subprocess
import importlib.util
import types
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
# Helper to ensure cross_platform is a package in sys.modules
def _ensure_cross_platform_package():
    """Ensures 'cross_platform' is a package in sys.modules for sub-module mocking."""
    if 'cross_platform' not in sys.modules:
        cross_platform_pkg = types.ModuleType('cross_platform')
        cross_platform_pkg.__path__ = [str(PYSCRIPTS_DIR / 'cross_platform')] # Essential for it to be a package
        sys.modules['cross_platform'] = cross_platform_pkg
    elif not hasattr(sys.modules['cross_platform'], '__path__'):
        # If it exists but isn't marked as a package, fix it
        sys.modules['cross_platform'].__path__ = [str(PYSCRIPTS_DIR / 'cross_platform')]


# Reference to the loaded module, needed for patching. Initialized after module load.
otc_module = None

@pytest.fixture(autouse=True)
def manage_clipboard_mock(monkeypatch):
    global LAST_CLIP
    LAST_CLIP = None # Reset for each test

    _ensure_cross_platform_package()

    # Create a mock clipboard_utils module
    mock_clipboard_utils_name = 'cross_platform.clipboard_utils'
    mock_clipboard_utils_mod = types.ModuleType(mock_clipboard_utils_name)
    
    # Define the mock set_clipboard function
    def new_fake_set_clipboard(text):
        global LAST_CLIP
        LAST_CLIP = text
    mock_clipboard_utils_mod.set_clipboard = new_fake_set_clipboard
    mock_clipboard_utils_mod.get_clipboard = lambda: "mocked clipboard content" # Add for completeness if ever used

    # Place the mock module into sys.modules
    monkeypatch.setitem(sys.modules, mock_clipboard_utils_name, mock_clipboard_utils_mod)
    # Also attach it to the mock 'cross_platform' package
    monkeypatch.setattr(sys.modules['cross_platform'], 'clipboard_utils', mock_clipboard_utils_mod)

    # Patch directly onto the otc_module IF it's already loaded (for direct calls within tests)
    # This ensures that otc_module's local 'set_clipboard' reference points to our mock.
    if otc_module: # Check if the script module has been loaded yet
        monkeypatch.setattr(otc_module, 'set_clipboard', new_fake_set_clipboard, raising=False)


MOCKED_HISTORY_COMMANDS = []
class FakeHistoryUtils:
    def __init__(self): self.shell_type = "mocked_shell"
    def get_nth_recent_command(self, n: int):
        global MOCKED_HISTORY_COMMANDS
        if MOCKED_HISTORY_COMMANDS is None: return None # Guard against uninitialized
        return MOCKED_HISTORY_COMMANDS[n-1] if 0 < n <= len(MOCKED_HISTORY_COMMANDS) else None

@pytest.fixture
def mock_history_utils(monkeypatch):
    global MOCKED_HISTORY_COMMANDS; MOCKED_HISTORY_COMMANDS = [] # Reset for each test
    
    _ensure_cross_platform_package()

    history_utils_mod_name = 'cross_platform.history_utils'
    mock_history_utils_mod = types.ModuleType(history_utils_mod_name)
    mock_history_utils_mod.HistoryUtils = FakeHistoryUtils # Attach the mock class
    
    monkeypatch.setitem(sys.modules, history_utils_mod_name, mock_history_utils_mod)
    monkeypatch.setattr(sys.modules['cross_platform'], 'history_utils', mock_history_utils_mod)
    
    # Patch directly onto the otc_module if it's already loaded
    # This is critical for tests that call otc_module.run_command_and_copy_main directly
    if otc_module:
        monkeypatch.setattr(otc_module, 'HistoryUtils', FakeHistoryUtils, raising=False)
    
    return FakeHistoryUtils


# --- Load the script under test ---
# This part is critical. We need to ensure all mocks are in place BEFORE the script attempts to import
# 'cross_platform.clipboard_utils' or 'cross_platform.history_utils'.
# The @pytest.fixture(autouse=True) for manage_clipboard_mock ensures it runs before tests.
# For the initial module load for `otc_module`, we need to make sure the mocks are ready.
try:
    # Ensure parent package 'cross_platform' and its submodules are set up *before* importing otc_module
    _ensure_cross_platform_package()

    # Pre-populate mocks for clipboard_utils and history_utils before the script under test is loaded
    # This ensures that when output_to_clipboard.py does its initial imports, it finds our mocks.
    # clipboard_utils:
    mock_cl_utils_name = 'cross_platform.clipboard_utils'
    if mock_cl_utils_name not in sys.modules:
        _cl_mod_temp = types.ModuleType(mock_cl_utils_name)
        _cl_mod_temp.set_clipboard = lambda x: None # Placeholder
        _cl_mod_temp.get_clipboard = lambda: ""
        sys.modules[mock_cl_utils_name] = _cl_mod_temp
        setattr(sys.modules['cross_platform'], 'clipboard_utils', _cl_mod_temp)

    # history_utils:
    mock_hist_utils_name = 'cross_platform.history_utils'
    if mock_hist_utils_name not in sys.modules:
        _hist_mod_temp = types.ModuleType(mock_hist_utils_name)
        _hist_mod_temp.HistoryUtils = lambda: None # Placeholder
        sys.modules[mock_hist_utils_name] = _hist_mod_temp
        setattr(sys.modules['cross_platform'], 'history_utils', _hist_mod_temp)


    otc_module_spec = importlib.util.spec_from_file_location("otc_module", str(SCRIPT_PATH))
    if otc_module_spec is None or otc_module_spec.loader is None:
        raise ImportError(f"Could not create module spec for {SCRIPT_PATH}")
    
    # Assign to global otc_module BEFORE exec_module so fixtures can find it.
    otc_module = importlib.util.module_from_spec(otc_module_spec)
    sys.modules['otc_module'] = otc_module # Makes it accessible for patching and for runpy context
    otc_module_spec.loader.exec_module(otc_module)

    # After loading, the autouse fixture 'manage_clipboard_mock' will apply its specific patches
    # to the now loaded otc_module (if it has `set_clipboard` directly) and the sys.modules entry.
    # The HistoryUtils mock will also be applied by its fixture.

except FileNotFoundError as e_fnf:
    pytest.fail(f"Importlib setup failed (FileNotFoundError): {e_fnf}\nSCRIPT_PATH was: {SCRIPT_PATH}", pytrace=False)
except Exception as e_imp:
    pytest.fail(f"Unexpected error during importlib setup: {e_imp}\nSCRIPT_PATH was: {SCRIPT_PATH}", pytrace=False)

# --- Test Helper ---
def run_otc_script_with_argv(argv_list, monkeypatch):
    monkeypatch.setattr(sys, "argv", argv_list)
    # runpy executes the script, which will re-import its dependencies.
    # The pre-existing mocks in sys.modules (set up by fixtures) will be used.
    # Also, ensure otc_module's HistoryUtils is the mock before runpy call.
    # The mock_history_utils fixture should have handled this for 'otc_module'.
    runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

@pytest.fixture
def mock_rich_console_input(monkeypatch):
    mock_input_method = mock.Mock()
    # Patch rich.console.Console.input globally so instances created by runpy-executed script get it.
    monkeypatch.setattr("rich.console.Console.input", mock_input_method)
    return mock_input_method

# --- Tests ---
# Ensure manage_clipboard_mock (autouse) has run and patched otc_module.set_clipboard
def test_direct_command_execution_success(monkeypatch, capsys, mock_rich_console_input):
    class FakeResult: stdout = "direct_out\n"; stderr = ""; returncode = 0
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: FakeResult())
    
    _op_ok, _user_cancel, _has_err, exit_c = otc_module.run_command_and_copy_main(
        command_parts=['echo', 'direct_hello'], replay_nth=None, no_stats=True, wrap=False
    )
    assert exit_c == 0
    
    out_cap, err_cap = capsys.readouterr()
    assert "Copied command output to clipboard." in out_cap
    assert LAST_CLIP == "direct_out"
    assert err_cap == "" # Stats are suppressed by no_stats=True, so stderr should be empty

def test_direct_command_execution_failure(monkeypatch, capsys, mock_rich_console_input):
    class FakeResult: stdout = ""; stderr = "direct_err_msg"; returncode = 1
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: FakeResult())

    _op_ok, _user_cancel, _has_err, exit_c = otc_module.run_command_and_copy_main(
        command_parts=['cmd_direct_fail'], replay_nth=None, no_stats=True, wrap=False
    )
    assert exit_c == 0

    out_cap, err_cap = capsys.readouterr()
    assert "Copied command output to clipboard." in out_cap
    assert "Command 'cmd_direct_fail' exited with status 1" in err_cap
    assert LAST_CLIP == "direct_err_msg"
    # CORRECTED: Removed Rich tag from assertion
    assert err_cap.strip().startswith("[WARNING]") # Ensure warning is there, but no stats

# --- New Tests for --wrap functionality ---
def test_direct_command_execution_with_wrap(monkeypatch, capsys):
    command_str = "ls -l"
    fake_output = "total 0\n-rw-r--r-- 1 user user 0 Jun 21 10:00 file.txt"
    class FakeResult: stdout = fake_output + "\n"; stderr = ""; returncode = 0
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: FakeResult())
    
    _op_ok, _user_cancel, _has_err, exit_c = otc_module.run_command_and_copy_main(
        command_parts=[command_str], replay_nth=None, no_stats=False, wrap=True # Changed no_stats to False
    )
    assert exit_c == 0
    out_cap, err_cap = capsys.readouterr()
    assert "Copied command output to clipboard." in out_cap
    
    expected_clipboard = f"$ {command_str}\n```\n{fake_output}\n```"
    assert LAST_CLIP == expected_clipboard
    # Checking for wrapping mode in stderr because stats now go there
    assert "Wrapping Mode" in err_cap # More robust check for table presence
    assert "Wrapped (command + code block)" in err_cap # Check the specific value

def test_replay_history_with_wrap(monkeypatch, capsys, mock_history_utils, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS; MOCKED_HISTORY_COMMANDS = ["my_command_history", "another_cmd"]
    mock_rich_console_input.return_value = 'y'
    
    command_from_history = "my_command_history"
    fake_output = "History command output here"
    def fake_subprocess_run(cmd_str, shell, capture_output, text, check):
        assert cmd_str == command_from_history
        return types.SimpleNamespace(stdout=fake_output + "\n", stderr="", returncode=0)
    monkeypatch.setattr(subprocess, 'run', fake_subprocess_run)

    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '-r', '1', '-w'], monkeypatch) # Removed --no-stats
    assert e.value.code == 0

    out_cap, err_cap = capsys.readouterr()
    assert "Copied command output to clipboard." in out_cap
    
    expected_clipboard = f"$ {command_from_history}\n```\n{fake_output}\n```"
    assert LAST_CLIP == expected_clipboard
    # Checking for wrapping mode in stderr because stats now go there
    assert "Wrapping Mode" in err_cap # More robust check
    assert "Wrapped (command + code block)" in err_cap # Check the specific value


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
    global MOCKED_HISTORY_COMMANDS; MOCKED_HISTORY_COMMANDS = ["baz", "bar", "foo"]
    mock_rich_console_input.return_value = 'y'
    
    def fake_subprocess_run(cmd_str, shell, capture_output, text, check):
        assert cmd_str == "bar"
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
    # CORRECTED: Ensure info messages are there, but no stats. Removed Rich tag.
    assert err_cap.strip().startswith("[INFO]") 

def test_replay_default_N_no_args_success(monkeypatch, capsys, mock_history_utils, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS; MOCKED_HISTORY_COMMANDS = ["echo hello default", "ls -la"]
    mock_rich_console_input.return_value = 'y'
    monkeypatch.setattr(subprocess, 'run', 
                        lambda cmd_str, **kwargs: types.SimpleNamespace(stdout="output from echo default\n", stderr="", returncode=0) 
                        if cmd_str == "echo hello default" else pytest.fail(f"Unexpected command: {cmd_str}"))
    
    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '--no-stats'], monkeypatch)
    assert e.value.code == 0

    out_cap, err_cap = capsys.readouterr()
    assert "Attempting to replay history entry N=1" in err_cap
    assert "Found history command: 'echo hello default'" in err_cap
    assert "Copied command output to clipboard." in out_cap
    assert LAST_CLIP == "output from echo default"
    # CORRECTED: Ensure info messages are there, but no stats. Removed Rich tag.
    assert err_cap.strip().startswith("[INFO]") 

@pytest.mark.parametrize("problematic_command_in_history", [
    f"{SCRIPT_PATH.name} -r 2", f"python {SCRIPT_PATH.name} --other-arg", f"./{SCRIPT_PATH.name}",
    f"bash {SCRIPT_PATH.name} run", f"{SCRIPT_PATH.stem} -r 1", f"python {SCRIPT_PATH.stem} --arg"
])
def test_replay_loop_prevention(monkeypatch, capsys, mock_history_utils, problematic_command_in_history, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS; MOCKED_HISTORY_COMMANDS = [problematic_command_in_history, "other"]
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
    global MOCKED_HISTORY_COMMANDS; MOCKED_HISTORY_COMMANDS = ["history_cmd"]
    
    def fake_run(cmd_parts_list_or_str, shell, capture_output, text, check):
        assert "echo test command" in cmd_parts_list_or_str
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
    global MOCKED_HISTORY_COMMANDS; MOCKED_HISTORY_COMMANDS = ["one cmd"]
    
    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '-r', '2', '--no-stats'], monkeypatch)
    assert e.value.code == 1
    _out, err = capsys.readouterr()
    assert "Failed to retrieve the 2nd command from history." in err

def test_replay_user_cancel_N_input(monkeypatch, capsys, mock_history_utils, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS; MOCKED_HISTORY_COMMANDS = ["cmd_to_cancel_N"]
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail("subprocess.run should not be called if user cancels"))
    mock_rich_console_input.return_value = 'n'
    
    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '-r', '1', '--no-stats'], monkeypatch)
    assert e.value.code == 0
    
    _out_cap, err_cap = capsys.readouterr()
    assert "User cancelled re-run." in err_cap
    assert LAST_CLIP is None

def test_replay_user_cancel_default_input(monkeypatch, capsys, mock_history_utils, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS; MOCKED_HISTORY_COMMANDS = ["cmd_to_cancel_def"]
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail("subprocess.run should not be called"))
    mock_rich_console_input.return_value = 'n'

    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '--no-stats'], monkeypatch)
    assert e.value.code == 0
    
    _out, err = capsys.readouterr()
    assert "User cancelled re-run." in err
    assert LAST_CLIP is None

def test_replay_eof_error_on_input(monkeypatch, capsys, mock_history_utils, mock_rich_console_input):
    global MOCKED_HISTORY_COMMANDS; MOCKED_HISTORY_COMMANDS = ["cmd_eof"]
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail("subprocess.run should not be called"))
    mock_rich_console_input.side_effect = EOFError

    with pytest.raises(SystemExit) as e:
        run_otc_script_with_argv([str(SCRIPT_PATH), '-r', '1', '--no-stats'], monkeypatch)
    assert e.value.code == 0
    
    _out, err = capsys.readouterr()
    assert "No input for confirmation (EOFError). Assuming 'No'." in err
    assert "User cancelled re-run." in err
    assert LAST_CLIP is None
