# tests/run_history_process_test.py
import pytest
import os
import subprocess # For FileNotFoundError, CalledProcessError types
import sys # For monkeypatching sys.argv and for stderr in run_rhp_main
from unittest.mock import MagicMock # For mocking shlex module in one test
import shlex # For constructing expected verbose output string

# Import the main function from your script
from run_history_process import main
import run_history_process as rhp_module # To access internals like rhp_module.shlex


# Helper to run `main` with monkeypatched sys.argv and capture output
def run_rhp_main(capsys, monkeypatch, args_list):
    """
    Runs the main() function from run_history_process.py with specified arguments.
    Captures the returned exit code (if main returns one) or the code from SystemExit.
    Also captures stdout/stderr.
    """
    # Prepend the script name, as sys.argv[0] is typically the script path
    full_args = ['run_history_process.py'] + args_list
    monkeypatch.setattr(sys, 'argv', full_args)
    
    actual_exit_code = None # Initialize
    
    try:
        # Call the main function from your script.
        # It is designed to RETURN an integer exit code in most paths.
        # Argparse errors within main() (from parser.error()) WILL call sys.exit(), raising SystemExit.
        returned_value_from_main = main()
        actual_exit_code = returned_value_from_main # Capture the direct return value
    except SystemExit as e:
        actual_exit_code = e.code # Capture exit code if sys.exit() was called (e.g., by argparse)
    except Exception:
        # If any other unhandled exception occurs in main(), print it and re-raise
        print(f"--- Unhandled exception in main() during test run with args: {args_list} ---", file=sys.stderr)
        raise

    captured = capsys.readouterr()
    return actual_exit_code, captured.out, captured.err

# --- Test Cases ---

def test_no_history_output(capsys, monkeypatch, mock_atuin_history):
    mock_atuin_history.set_history_output([])
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['rhp-insert'])
    assert exit_code == 1, f"STDOUT: {out}\nSTDERR: {err}"
    assert out == ""

    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['echo', '{}'])
    assert exit_code == 1, f"STDOUT: {out}\nSTDERR: {err}"
    assert "Error: No paths found in history." in err

def test_atuin_not_found(capsys, monkeypatch, mock_atuin_history):
    mock_atuin_history.set_history_exception(FileNotFoundError("atuin command not found test error"))
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['rhp-insert', '-v'])
    assert exit_code == 1, f"STDOUT: {out}\nSTDERR: {err}"
    assert "Error: 'atuin' command not found" in err

def test_atuin_called_process_error(capsys, monkeypatch, mock_atuin_history):
    mock_cpe = subprocess.CalledProcessError(
        returncode=1, cmd=['atuin', 'history', 'list'], stderr="Atuin internal test error"
    )
    mock_atuin_history.set_history_exception(mock_cpe)
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['rhp-insert', '-v'])
    assert exit_code == 1, f"STDOUT: {out}\nSTDERR: {err}"
    assert "Error fetching Atuin history" in err
    assert "Atuin internal test error" in err

def test_basic_path_identification(capsys, monkeypatch, mock_atuin_history):
    mock_atuin_history.set_history_output([
        "cmd1 /abs/path/file.txt",
        "cmd2 other/path.log",
        "cmd3 ~/homefile.sh",
        "cmd4 ./local.data",
        "cmd5 no_path_here",
        "cmd6 another /abs/path/file.txt"
    ])
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['rhp-insert'])
    assert exit_code == 0, f"STDOUT: {out}\nSTDERR: {err}"
    assert out.strip() == os.path.normpath("/abs/path/file.txt")

    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['-i', '3', 'rhp-insert'])
    assert exit_code == 0, f"STDOUT: {out}\nSTDERR: {err}"
    assert out.strip() == os.path.normpath(os.path.expanduser("~/homefile.sh"))

    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['-i', '4', 'rhp-insert'])
    assert exit_code == 0, f"STDOUT: {out}\nSTDERR: {err}"
    assert out.strip() == os.path.normpath("./local.data")


def test_path_with_dot_extension(capsys, monkeypatch, mock_atuin_history):
    mock_atuin_history.set_history_output(["nvim script.py", "cat data.json", "run 1.2.3"])
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['rhp-insert'])
    assert exit_code == 0, f"STDOUT: {out}\nSTDERR: {err}"
    assert out.strip() == "script.py"

    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['-i', '2', 'rhp-insert'])
    assert exit_code == 0, f"STDOUT: {out}\nSTDERR: {err}"
    assert out.strip() == "data.json"

def test_cd_command_path(capsys, monkeypatch, mock_atuin_history):
    mock_atuin_history.set_history_output(["ls some.file", "cd mydir", "cat another.file"])
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['rhp-insert', '-i', '2'])
    assert exit_code == 0, f"STDOUT: {out}\nSTDERR: {err}"
    assert out.strip() == "mydir"

def test_uniqueness_of_paths(capsys, monkeypatch, mock_atuin_history):
    mock_atuin_history.set_history_output([
        "cat /a/b/c.txt",
        "ls /a/b/c.txt",
        "vim /x/y/z.py",
        "echo /a/b/c.txt"
    ])
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['rhp-insert'])
    assert exit_code == 0, f"STDOUT: {out}\nSTDERR: {err}"
    assert out.strip() == "/a/b/c.txt"
    
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['-i', '2', 'rhp-insert'])
    assert exit_code == 0, f"STDOUT: {out}\nSTDERR: {err}"
    assert out.strip() == "/x/y/z.py"

def test_pattern_matching_simple(capsys, monkeypatch, mock_atuin_history):
    mock_atuin_history.set_history_output([
        "cat report.pdf",
        "nvim main_script.py",
        "cat data.json",
        "python utils/helpers.py",
        "gedit notes.txt"
    ])
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['-p', '*.py', 'rhp-insert'])
    assert exit_code == 0, f"STDOUT: {out}\nSTDERR: {err}"
    assert out.strip() == "main_script.py"

    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['-p', '*.py', '-i', '2', 'rhp-insert'])
    assert exit_code == 0, f"STDOUT: {out}\nSTDERR: {err}"
    assert out.strip() == os.path.normpath("utils/helpers.py")

    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['-p', 'utils/*', 'rhp-insert'])
    assert exit_code == 0, f"STDOUT: {out}\nSTDERR: {err}"
    assert out.strip() == os.path.normpath("utils/helpers.py")

def test_pattern_no_match(capsys, monkeypatch, mock_atuin_history):
    mock_atuin_history.set_history_output(["cat file.txt", "nvim script.py"])
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['-p', '*.log', 'rhp-insert'])
    assert exit_code == 1, f"STDOUT: {out}\nSTDERR: {err}"
    assert out == ""

    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['-p', '*.log', 'echo', '{}'])
    assert exit_code == 1, f"STDOUT: {out}\nSTDERR: {err}"
    assert "Error: No paths found matching pattern '*.log'" in err

def test_index_out_of_bounds(capsys, monkeypatch, mock_atuin_history):
    mock_atuin_history.set_history_output(["cat file1.txt", "cat file2.txt"])
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['-i', '3', 'rhp-insert'])
    assert exit_code == 1, f"STDOUT: {out}\nSTDERR: {err}"
    assert out == ""

    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['-i', '3', 'echo', '{}'])
    assert exit_code == 1, f"STDOUT: {out}\nSTDERR: {err}"
    assert "Error: Not enough paths to satisfy index 3" in err
    assert "Found 2 paths." in err

def test_invalid_index_zero_or_negative(capsys, monkeypatch, mock_atuin_history):
    mock_atuin_history.set_history_output(["cat file1.txt"])
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['-i', '0', 'echo', '{}'])
    assert exit_code == 1, f"STDOUT: {out}\nSTDERR: {err}"
    assert "Error: --index must be a positive integer" in err
    
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['-i', '-1', 'echo', '{}'])
    assert exit_code == 1, f"STDOUT: {out}\nSTDERR: {err}"
    assert "Error: --index must be a positive integer" in err

def test_command_execution_placeholder(capsys, monkeypatch, mock_atuin_history):
    mock_atuin_history.set_history_output(["vim /my/doc.txt"])
    
    expected_nvim_cmd_list = ['nvim', '/my/doc.txt']
    mock_atuin_history.mock_specific_command_execution(expected_nvim_cmd_list, returncode=0)
    
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['nvim', '{}'])
    assert exit_code == 0, f"STDOUT: {out}\nSTDERR: {err}"
    
    called_correctly = False
    for call_obj in mock_atuin_history.main_subprocess_mock.call_args_list:
        args_called, kwargs_called = call_obj
        if args_called[0] == expected_nvim_cmd_list:
            assert kwargs_called.get('check') == False
            called_correctly = True
            break
    assert called_correctly, f"Expected command {expected_nvim_cmd_list} not called as configured."

def test_command_execution_append(capsys, monkeypatch, mock_atuin_history):
    mock_atuin_history.set_history_output(["ls mydir/"])
    
    expected_ls_cmd_list = ['ls', '-l', 'mydir'] 
    mock_atuin_history.mock_specific_command_execution(expected_ls_cmd_list, returncode=0)
        
    # Use '--' to separate script args from command_template args if they might clash
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['--', 'ls', '-l'])
    assert exit_code == 0, f"STDOUT: {out}\nSTDERR: {err}"

    called_correctly = False
    for call_obj in mock_atuin_history.main_subprocess_mock.call_args_list:
        args_called, kwargs_called = call_obj
        if args_called[0] == expected_ls_cmd_list:
            assert kwargs_called.get('check') == False
            called_correctly = True
            break
    assert called_correctly, f"Expected command {expected_ls_cmd_list} not called as configured."

def test_command_execution_failure_command_not_found(capsys, monkeypatch, mock_atuin_history):
    mock_atuin_history.set_history_output(["input_cmd some/file"])
    
    command_that_will_be_run_list = ['nonexistentcmd', 'some/file']
    
    mock_atuin_history.mock_specific_command_to_raise(
        command_that_will_be_run_list, 
        FileNotFoundError(f"Test mock: No such file or directory: '{command_that_will_be_run_list[0]}'")
    )
    
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['nonexistentcmd', '{}'])
    
    assert exit_code == 127, f"STDOUT: {out}\nSTDERR: {err}"
    assert f"Error: Command '{command_that_will_be_run_list[0]}' not found." in err

def test_command_execution_failure_non_zero_exit(capsys, monkeypatch, mock_atuin_history):
    mock_atuin_history.set_history_output(["failing_cmd /some/arg"])
    
    expected_failing_cmd_list = ['failing_cmd', '/some/arg']
    mock_atuin_history.mock_specific_command_execution(expected_failing_cmd_list, returncode=5)
    
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['failing_cmd', '{}'])
    assert exit_code == 5, f"STDOUT: {out}\nSTDERR: {err}"

def test_verbose_mode_output(capsys, monkeypatch, mock_atuin_history):
    mock_atuin_history.set_history_output(["cat some/file.txt", "nvim other/doc.md"])
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['-v', 'rhp-insert'])
    assert exit_code == 0, f"STDOUT: {out}\nSTDERR: {err}"
    assert out.strip() == "some/file.txt"
    assert "Verbose mode enabled." in err
    assert "Fetched 2 lines" in err
    assert "Processing history entry 1/2: cat some/file.txt" in err
    assert "Collected unique path: 'some/file.txt'" in err
    assert "Processing history entry 2/2: nvim other/doc.md" in err
    assert "Collected unique path: 'other/doc.md'" in err
    assert "No pattern specified" in err
    assert "Selected path at 1-based index 1: 'some/file.txt'" in err

    mock_atuin_history.set_history_output(["mycmd my/file"])
    command_parts_for_exec = ['mycmd', 'my/file']
    mock_atuin_history.mock_specific_command_execution(command_parts_for_exec, returncode=0)
    
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['-v', '--', 'mycmd'])
    assert exit_code == 0, f"STDOUT: {out}\nSTDERR: {err}"
    
    expected_exec_log = f"Executing: {shlex.join(command_parts_for_exec)}" # shlex.join for robust quoting display
    # Or, if your script uses ' '.join(shlex.quote(c) for c in cmd):
    # expected_exec_log = f"Executing: {' '.join(shlex.quote(c) for c in command_parts_for_exec)}"
    assert expected_exec_log in err, f"Expected log '{expected_exec_log}' not found in STDERR:\n{err}"


def test_shlex_split_error_fallback(capsys, monkeypatch, mock_atuin_history):
    original_shlex_split_func = rhp_module.shlex.split
    
    def shlex_side_effect_for_test(cmd_line_str, comments=False, posix=True):
        if "malformed command line with ' unclosed quote" in cmd_line_str:
            raise ValueError("shlex split error due to unclosed quote")
        return original_shlex_split_func(cmd_line_str, comments=comments, posix=posix)
    
    mock_shlex_module_obj = MagicMock()
    mock_shlex_module_obj.split = MagicMock(side_effect=shlex_side_effect_for_test)
    
    monkeypatch.setattr(rhp_module, 'shlex', mock_shlex_module_obj)

    mock_atuin_history.set_history_output([
        "cmd1 malformed command line with ' unclosed quote", 
        "cmd2 /actual/ok/path.txt"
    ])
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['-v', 'rhp-insert'])
    
    assert exit_code == 0, f"STDOUT: {out}\nSTDERR: {err}"
    assert out.strip() == "/actual/ok/path.txt"
    assert "Could not shlex.split: 'cmd1 malformed command line with ' unclosed quote'" in err
    assert "falling back to simple space split" in err

def test_path_normalization_and_tilde_expansion(capsys, monkeypatch, mock_atuin_history):
    home_dir = os.path.expanduser("~")
    
    mock_atuin_history.set_history_output([
        "cmd1 ././file1.txt",
        "cmd2 ~/../sibling_of_home.log",
        "cmd3 /abs/path/to/../../other_abs_path/./file3.sh"
    ])
    
    expected_path1 = os.path.normpath("file1.txt")
    expected_path2 = os.path.normpath(os.path.join(os.path.dirname(home_dir), "sibling_of_home.log"))
    expected_path3 = os.path.normpath("/abs/other_abs_path/file3.sh")

    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['-i', '1', 'rhp-insert'])
    assert exit_code == 0, f"Output: {out}\nError: {err}"
    assert out.strip() == expected_path1

    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['-i', '2', 'rhp-insert'])
    assert exit_code == 0, f"Output: {out}\nError: {err}"
    assert out.strip() == expected_path2
    
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['-i', '3', 'rhp-insert'])
    assert exit_code == 0, f"Output: {out}\nError: {err}"
    assert out.strip() == expected_path3

def test_rhp_insert_in_command_template(capsys, monkeypatch, mock_atuin_history):
    mock_atuin_history.set_history_output(["cat /my/file.txt"])
    exit_code, out, err = run_rhp_main(capsys, monkeypatch, ['echo', '{}', 'rhp-insert'])
    assert exit_code == 0, f"STDOUT: {out}\nSTDERR: {err}"
    assert out.strip() == "/my/file.txt" 
    
    is_atuin_call_found = False
    non_atuin_call_found = False
    for call_obj in mock_atuin_history.main_subprocess_mock.call_args_list:
        args_called, _ = call_obj
        if args_called[0][0] == 'atuin':
            is_atuin_call_found = True
        else:
            non_atuin_call_found = True
            # print(f"DEBUG: Found non-atuin call: {args_called[0]}", file=sys.stderr) # For debugging
    
    assert is_atuin_call_found, "Atuin history call was expected"
    assert not non_atuin_call_found, "No other command should be executed in rhp-insert mode"
