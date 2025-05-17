# tests/test_output_to_clipboard.py
import sys
import os
import runpy
import subprocess
import importlib.util
import types
import builtins
import pytest
from pathlib import Path

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
    LAST_CLIP = None # Reset for each test
    clipboard_mod = types.ModuleType('cross_platform.clipboard_utils')
    def fake_set_clipboard(text):
        global LAST_CLIP
        LAST_CLIP = text
    clipboard_mod.set_clipboard = fake_set_clipboard # type: ignore
    
    # Ensure 'cross_platform' itself exists as a module in sys.modules
    if 'cross_platform' not in sys.modules:
        cross_pkg = types.ModuleType('cross_platform')
        sys.modules['cross_platform'] = cross_pkg
    else:
        cross_pkg = sys.modules['cross_platform']
        
    cross_pkg.clipboard_utils = clipboard_mod # type: ignore
    monkeypatch.setitem(sys.modules, 'cross_platform.clipboard_utils', clipboard_mod)

# --- Mock HistoryUtils ---
MOCKED_HISTORY_COMMANDS = [] # Stores commands with most recent at index 0

class FakeHistoryUtils:
    def __init__(self):
        self.shell_type = "mocked_shell" 
        global MOCKED_HISTORY_COMMANDS
        # This is just for internal state, get_nth_recent_command will re-read global
        self._commands_on_init = list(MOCKED_HISTORY_COMMANDS) 
        # Simulate write_debug if needed by tests, or just make it a no-op
        self.write_debug_calls = []

    def get_nth_recent_command(self, n: int):
        global MOCKED_HISTORY_COMMANDS
        # N=1 is most recent, which is MOCKED_HISTORY_COMMANDS[0]
        if 0 < n <= len(MOCKED_HISTORY_COMMANDS):
            return MOCKED_HISTORY_COMMANDS[n-1] 
        return None
    
    # Mocked write_debug for HistoryUtils if it were to use self.write_debug
    def _write_debug(self, msg, channel): # Renamed to avoid conflict if real one is classmethod/static
        self.write_debug_calls.append((msg, channel))


@pytest.fixture
def mock_history_utils(monkeypatch):
    """Fixture to mock cross_platform.history_utils.HistoryUtils."""
    global MOCKED_HISTORY_COMMANDS
    MOCKED_HISTORY_COMMANDS = [] # Reset for each test that uses this fixture

    # Ensure 'cross_platform' module exists
    if 'cross_platform' not in sys.modules:
        sys.modules['cross_platform'] = types.ModuleType('cross_platform')

    # Create a dummy module for history_utils to attach the FakeHistoryUtils to
    # This ensures that `from cross_platform.history_utils import HistoryUtils` works
    history_utils_mod_spec = importlib.util.spec_from_loader('cross_platform.history_utils', loader=None)
    if history_utils_mod_spec is None:
        history_utils_mod = types.ModuleType('cross_platform.history_utils')
    else:
        history_utils_mod = importlib.util.module_from_spec(history_utils_mod_spec)
    
    history_utils_mod.HistoryUtils = FakeHistoryUtils # type: ignore
    sys.modules['cross_platform.history_utils'] = history_utils_mod
    sys.modules['cross_platform'].history_utils = history_utils_mod # type: ignore

    # Mock dependencies of the *real* HistoryUtils in case any part of it is called
    # or if FakeHistoryUtils were to call super(). For now, FakeHistoryUtils is standalone.
    if 'cross_platform.debug_utils' not in sys.modules:
        debug_utils_mod = types.ModuleType('cross_platform.debug_utils')
        debug_utils_mod.write_debug = lambda *args, **kwargs: None # type: ignore
        debug_utils_mod.console = types.SimpleNamespace(print=lambda *args, **kwargs: None) # type: ignore
        sys.modules['cross_platform.debug_utils'] = debug_utils_mod
        sys.modules['cross_platform'].debug_utils = debug_utils_mod # type: ignore

    if 'cross_platform.system_utils' not in sys.modules:
        system_utils_mod = types.ModuleType('cross_platform.system_utils')
        class MockSystemUtils:
            def __init__(self): self.os_name = "linux"; self.is_admin = False
            def run_command(self, cmd, **kwargs): return ""
        system_utils_mod.SystemUtils = MockSystemUtils # type: ignore
        sys.modules['cross_platform.system_utils'] = system_utils_mod
        sys.modules['cross_platform'].system_utils = system_utils_mod # type: ignore
        
    return FakeHistoryUtils # Not strictly needed to return, but can be useful

# --- Tests for output_to_clipboard.py ---

def test_run_command_and_copy_success(monkeypatch, capsys, mock_history_utils):
    class FakeResult:
        stdout = "out\n"; stderr = ""; returncode = 0
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: FakeResult())
    
    spec = importlib.util.spec_from_file_location("otc", SCRIPT_PATH)
    otc = importlib.util.module_from_spec(spec) # type: ignore
    sys.modules[spec.name] = otc # type: ignore # Make otc importable if it imports itself
    spec.loader.exec_module(otc) # type: ignore

    otc.run_command_and_copy(['echo', 'hello'])
    out, err = capsys.readouterr()
    assert "Copied command output to clipboard." in out
    assert LAST_CLIP == "out"
    assert err == ""

def test_run_command_and_copy_failure(monkeypatch, capsys, mock_history_utils):
    class FakeResult:
        stdout = ""; stderr = "err"; returncode = 1
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: FakeResult())
    spec = importlib.util.spec_from_file_location("otc", SCRIPT_PATH)
    otc = importlib.util.module_from_spec(spec) #type: ignore
    sys.modules[spec.name] = otc #type: ignore
    spec.loader.exec_module(otc) #type: ignore
    otc.run_command_and_copy(['cmd'])
    out, err = capsys.readouterr()
    assert "Copied command output to clipboard." in out
    assert "Warning: Command 'cmd' exited with status 1" in err
    assert LAST_CLIP == "err"

def test_invalid_replay_history_negative_N(monkeypatch, capsys, mock_history_utils):
    monkeypatch.setattr(sys, 'argv', ['output_to_clipboard.py', '-r', '-1'])
    with pytest.raises(SystemExit) as e:
        runpy.run_path(SCRIPT_PATH, run_name="__main__")
    assert e.value.code == 1
    _out, err = capsys.readouterr()
    assert "[ERROR] Value for --replay-history (-r) must be positive." in err

def test_invalid_replay_history_zero_N(monkeypatch, capsys, mock_history_utils):
    monkeypatch.setattr(sys, 'argv', ['output_to_clipboard.py', '-r', '0'])
    with pytest.raises(SystemExit) as e:
        runpy.run_path(SCRIPT_PATH, run_name="__main__")
    assert e.value.code == 1
    _out, err = capsys.readouterr()
    assert "[ERROR] Value for --replay-history (-r) must be positive." in err


def test_replay_history_branch_explicit_N(monkeypatch, capsys, mock_history_utils):
    global MOCKED_HISTORY_COMMANDS
    MOCKED_HISTORY_COMMANDS = ["baz command", "bar command", "foo command"] # N=1: baz, N=2: bar
    
    # Mock subprocess.run for the replayed command "bar command"
    def fake_subprocess_run(cmd_str, shell, capture_output, text, check):
        assert cmd_str == "bar command" # Ensure the correct command is run
        return types.SimpleNamespace(stdout="val_from_bar\n", stderr="", returncode=0)
    monkeypatch.setattr(subprocess, 'run', fake_subprocess_run)
    monkeypatch.setattr(builtins, 'input', lambda prompt: 'y')
    monkeypatch.setattr(sys, 'argv', ['output_to_clipboard.py', '-r', '2'])
    
    runpy.run_path(SCRIPT_PATH, run_name="__main__")
    out, err = capsys.readouterr()

    assert f"[INFO] Attempting to replay history entry N=2..." in err
    assert f"[INFO] Found history command: 'bar command'" in err
    assert "User approved. Re-running: bar command" in err
    assert "Copied command output to clipboard." in out
    assert LAST_CLIP == "val_from_bar"

def test_history_branch_success_default_N_no_args(monkeypatch, capsys, mock_history_utils):
    global MOCKED_HISTORY_COMMANDS
    MOCKED_HISTORY_COMMANDS = ["echo hello default", "ls -la"] # N=1 is "echo hello default"

    monkeypatch.setattr(subprocess, 'run', lambda cmd_str, **kwargs: types.SimpleNamespace(stdout="output from echo default\n", stderr="", returncode=0) if cmd_str == "echo hello default" else None)
    monkeypatch.setattr(builtins, 'input', lambda prompt: 'y')
    # Script name can be anything, what matters is that no args follow.
    # Using a generic name to ensure Path(sys.argv[0]) works.
    monkeypatch.setattr(sys, 'argv', ['otc_script.py']) 

    runpy.run_path(SCRIPT_PATH, run_name="__main__")
    out, err = capsys.readouterr()

    assert "[INFO] Attempting to replay history entry N=1..." in err
    assert "[INFO] Found history command: 'echo hello default'" in err
    assert "User approved. Re-running: echo hello default" in err
    assert "Copied command output to clipboard." in out
    assert LAST_CLIP == "output from echo default"

@pytest.mark.parametrize("script_invocation_name", ["output_to_clipboard.py", "otc"])
@pytest.mark.parametrize("problematic_command_format", [
    "{script_name} -r 2",              # e.g. output_to_clipboard.py -r 2
    "python {script_name} --other-arg", # e.g. python output_to_clipboard.py --other-arg
    "./{script_name}",                  # e.g. ./output_to_clipboard.py
    "bash {script_name} run",           # e.g. bash output_to_clipboard.py run
])
def test_history_loop_prevention(monkeypatch, capsys, mock_history_utils, script_invocation_name, problematic_command_format):
    global MOCKED_HISTORY_COMMANDS
    
    # Construct the command that would cause a loop
    # Use a placeholder for the script name that will be formatted
    # The actual sys.argv[0] will be SCRIPT_PATH for runpy
    # So Path(sys.argv[0]).name will be 'output_to_clipboard.py'
    # And Path(sys.argv[0]).stem will be 'output_to_clipboard'
    
    # If script_invocation_name is 'otc' (simulating an alias or stem call)
    # and the history command is 'otc -r 1', loop should be caught.
    # If script_invocation_name is 'output_to_clipboard.py' (actual script name)
    # and history command is 'output_to_clipboard.py -r 1', loop should be caught.
    
    # For the test, sys.argv[0] when runpy.run_path is used is the SCRIPT_PATH.
    # So Path(sys.argv[0]).name will be 'output_to_clipboard.py'.
    # We need to ensure the loop prevention catches this.
    
    formatted_command = problematic_command_format.format(script_name=Path(SCRIPT_PATH).name)
    if script_invocation_name == "otc" and "{script_name}" not in problematic_command_format:
         # e.g. command is "otc -r 1", and script name is "output_to_clipboard.py", but might be aliased as otc
         # The check `first_cmd_part == script_name_stem` should catch this if stem is 'otc'
         # For testing, we ensure the history command uses a name that Path(SCRIPT_PATH).stem would match
         # if the script were named 'otc.py'
         if problematic_command_format.startswith("otc"): # like "otc -r 2"
            formatted_command = problematic_command_format.replace("otc", Path(SCRIPT_PATH).stem)


    MOCKED_HISTORY_COMMANDS = [formatted_command, "some other command"] 

    # This input shouldn't be reached if loop prevention works
    monkeypatch.setattr(builtins, 'input', lambda prompt: pytest.fail("Input should not be prompted if loop is detected."))
    
    # Simulate the script being called as `script_invocation_name` for its own sys.argv[0] perception
    # However, runpy uses SCRIPT_PATH. The internal logic uses Path(sys.argv[0]).name/stem.
    # So we set sys.argv for the script execution via runpy.
    monkeypatch.setattr(sys, 'argv', [script_invocation_name, '-r', '1'])


    with pytest.raises(SystemExit) as e:
        # When runpy executes SCRIPT_PATH, sys.argv inside the script will be what we set above.
        # The Path(sys.argv[0]) inside the script will correctly use `script_invocation_name`.
        # Wait, runpy.run_path sets sys.argv[0] to the path of the script being run.
        # So, inside SCRIPT_PATH, sys.argv[0] will be SCRIPT_PATH.
        # The loop prevention uses Path(sys.argv[0]).name and Path(sys.argv[0]).stem.
        # Path(SCRIPT_PATH).name is 'output_to_clipboard.py'
        # Path(SCRIPT_PATH).stem is 'output_to_clipboard'
        
        # Let's ensure the history command uses these values for the test.
        # This means `script_name` in `problematic_command_format` should be 'output_to_clipboard.py'
        # or 'output_to_clipboard' if it's a stem check.
        
        # Re-evaluate `formatted_command` based on actual SCRIPT_PATH name/stem
        actual_script_name = Path(SCRIPT_PATH).name
        actual_script_stem = Path(SCRIPT_PATH).stem

        if "{script_name}" in problematic_command_format:
             MOCKED_HISTORY_COMMANDS[0] = problematic_command_format.format(script_name=actual_script_name)
        elif "otc" in problematic_command_format and problematic_command_format.startswith("otc"):
             MOCKED_HISTORY_COMMANDS[0] = problematic_command_format.replace("otc", actual_script_stem)
        # else: it's a command like "python something.py" that needs actual_script_name in it.
        # This is covered by the first case.

        runpy.run_path(SCRIPT_PATH, run_name="__main__") # sys.argv for this run is already set by monkeypatch
    
    assert e.value.code == 1, f"Script should exit with 1 on loop prevention. Failed for history: '{MOCKED_HISTORY_COMMANDS[0]}'"
    _out, err = capsys.readouterr()
    assert f"appears to be an invocation of this script. Aborting to prevent a loop." in err
    assert MOCKED_HISTORY_COMMANDS[0] in err # Ensure the problematic command is mentioned


def test_replay_history_ignored_if_command_provided(monkeypatch, capsys, mock_history_utils):
    global MOCKED_HISTORY_COMMANDS
    MOCKED_HISTORY_COMMANDS = ["some history command"] # Should not be used

    # Mock subprocess.run for the explicit command 'echo test command'
    def fake_run(cmd_str, shell, capture_output, text, check):
        assert cmd_str == "echo test command" 
        return types.SimpleNamespace(stdout="hello_explicit\n", stderr="", returncode=0)
    monkeypatch.setattr(subprocess, 'run', fake_run)
    
    monkeypatch.setattr(sys, 'argv', ['output_to_clipboard.py', '-r', '1', 'echo', 'test', 'command'])
    
    runpy.run_path(SCRIPT_PATH, run_name="__main__")
    out, err = capsys.readouterr()
    assert "Copied command output to clipboard." in out
    assert LAST_CLIP == "hello_explicit"
    assert "[INFO] Attempting to replay history entry N=" not in err # History logic skipped

def test_history_command_not_found(monkeypatch, capsys, mock_history_utils):
    global MOCKED_HISTORY_COMMANDS
    MOCKED_HISTORY_COMMANDS = ["only one command"]

    monkeypatch.setattr(sys, 'argv', ['output_to_clipboard.py', '-r', '2']) # Request 2nd, but only 1 exists

    with pytest.raises(SystemExit) as e:
        runpy.run_path(SCRIPT_PATH, run_name="__main__")
    assert e.value.code == 1
    _out, err = capsys.readouterr()
    # Check for "2nd", "3rd", "Nth" etc.
    expected_msg_part = "Failed to retrieve the 2nd command from history."
    assert expected_msg_part in err

def test_replay_history_user_cancel_N(monkeypatch, capsys, mock_history_utils):
    global MOCKED_HISTORY_COMMANDS
    MOCKED_HISTORY_COMMANDS = ["command to cancel with N"]
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: pytest.fail("subprocess.run should not be called if user cancels"))
    monkeypatch.setattr(builtins, 'input', lambda prompt: 'n') # User says no
    monkeypatch.setattr(sys, 'argv', ['output_to_clipboard.py', '-r', '1'])

    with pytest.raises(SystemExit) as e:
        runpy.run_path(SCRIPT_PATH, run_name="__main__")
    assert e.value.code == 0 # Exits with 0 on user cancellation
    _out, err = capsys.readouterr()
    assert "[INFO] User cancelled re-run." in err
    assert "Copied command output to clipboard." not in _out

def test_replay_history_user_cancel_default(monkeypatch, capsys, mock_history_utils):
    global MOCKED_HISTORY_COMMANDS
    MOCKED_HISTORY_COMMANDS = ["command to cancel default"]
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: pytest.fail("subprocess.run should not be called"))
    monkeypatch.setattr(builtins, 'input', lambda prompt: 'n')
    monkeypatch.setattr(sys, 'argv', ['output_to_clipboard.py']) # No args, replay N=1

    with pytest.raises(SystemExit) as e:
        runpy.run_path(SCRIPT_PATH, run_name="__main__")
    assert e.value.code == 0
    _out, err = capsys.readouterr()
    assert "[INFO] User cancelled re-run." in err

def test_eof_error_on_input_behaves_as_cancel(monkeypatch, capsys, mock_history_utils):
    global MOCKED_HISTORY_COMMANDS
    MOCKED_HISTORY_COMMANDS = ["command with eof input"]
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: pytest.fail("subprocess.run should not be called"))
    
    def raise_eof(prompt):
        raise EOFError
    monkeypatch.setattr(builtins, 'input', raise_eof)
    monkeypatch.setattr(sys, 'argv', ['output_to_clipboard.py', '-r', '1'])

    with pytest.raises(SystemExit) as e:
        runpy.run_path(SCRIPT_PATH, run_name="__main__")
    assert e.value.code == 0 # Should exit gracefully, assuming 'no'
    _out, err = capsys.readouterr()
    assert "[WARNING] No input available for confirmation (EOFError). Assuming 'No'." in err
    assert "[INFO] User cancelled re-run." in err # This follows the 'no' path
