# test_batch_runner.py
import pytest
import subprocess
import sys
import os
import time
import json
from pathlib import Path
import shutil
import signal
from typing import Optional, List, Dict, Any # Corrected import line

# Assume batch_runner.py is in the same directory or accessible in PATH
# --- Determine the absolute path to the script ---
try:
    # If tests are in tests/ subdir relative to script
    SCRIPT_PATH = (Path(__file__).parent.parent / "batch_runner2.py").resolve(strict=True)
except FileNotFoundError:
    try:
        # If tests are in the same dir as script
        SCRIPT_PATH = (Path(__file__).parent / "batch_runner.py").resolve(strict=True)
    except FileNotFoundError:
        pytest.fail("Could not find batch_runner.py relative to the test file.", pytrace=False)

SCRIPT_NAME = SCRIPT_PATH.name # Keep for reference if needed, but use SCRIPT_PATH
PYTHON_EXEC = sys.executable # Use the same python interpreter running pytest

# --- Fixtures ---

@pytest.fixture(scope="function")
def test_dir(tmp_path):
    """Provides a temporary directory for each test function."""
    yield tmp_path
    # Cleanup happens automatically when tmp_path goes out of scope

@pytest.fixture(scope="function")
def batch_file(test_dir):
    """Provides the path to a batch file within the test directory."""
    return test_dir / "test_batch.cmds"

@pytest.fixture(scope="function")
def state_file(batch_file):
    """Provides the expected path to the state file."""
    # Resolve the batch file path first in case test_dir itself is relative
    state_dir = batch_file.resolve().parent
    return state_dir / ".batch_runner_state.json"

@pytest.fixture(scope="function")
def log_dir(batch_file):
    """Provides the expected path to the log directory."""
    # Resolve the batch file path first
    state_dir = batch_file.resolve().parent
    return state_dir / "logs"

# --- Helper Function (MODIFIED) ---

def run_script(args: list, cwd: Path, timeout_override: Optional[int] = None) -> subprocess.CompletedProcess:
    """Runs the batch_runner.py script with given arguments."""
    # *** USE THE ABSOLUTE PATH TO THE SCRIPT ***
    command = [PYTHON_EXEC, str(SCRIPT_PATH)] + args
    timeout_seconds = timeout_override if timeout_override is not None else 15 # Default timeout
    try:
        # Use a common environment, but ensure PATH is inherited correctly
        env = os.environ.copy()
        # Add flag to maybe disable rich colors if they interfere with parsing stdout
        # env['TERM'] = 'dumb' # Or 'NO_COLOR'='1' ? Test this if needed.

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding='utf-8', # Explicitly set encoding
            cwd=cwd, # Run script actions relative to the test directory
            check=False, # Don't raise exception on non-zero exit code from script itself
            timeout=timeout_seconds,
            env=env # Pass the environment
        )
        # Debugging output if failing unexpectedly
        # Check for common script errors vs test assertion errors
        script_errors = ["Traceback", "Error:", "Warning:"] # Case-sensitive check might miss rich tags like [red]Error[/red]
        # Let's check stderr for *any* content if returncode is non-zero, as script errors often go there
        if result.returncode != 0 and result.stderr:
             # Print only if it seems like a script crash, not just non-zero exit from user commands
             if "Traceback (most recent call last)" in result.stderr or "[red]Error" in result.stdout or "[red]Error" in result.stderr:
                 print(f"\n--- Test Run: Script Error Detected ---")
                 print(f"CMD: {' '.join(command)}")
                 print(f"CWD: {cwd}")
                 print(f"EXIT CODE: {result.returncode}")
                 print(f"STDOUT:\n{result.stdout}")
                 print(f"STDERR:\n{result.stderr}")
                 print(f"-------------------------------------\n")

        return result
    except subprocess.TimeoutExpired as e:
        # Capture output even on timeout
        stdout = e.stdout.decode('utf-8', errors='replace') if e.stdout else ""
        stderr = e.stderr.decode('utf-8', errors='replace') if e.stderr else ""
        print(f"Timeout expired running: {' '.join(command)}")
        print(f"Stdout: {stdout}")
        print(f"Stderr: {stderr}")
        pytest.fail(f"Script timed out after {timeout_seconds}s: {' '.join(command)}")


def wait_for_processes(state_data: dict, batch_key: str, timeout: int = 5):
    """Waits for processes listed in the state file to finish."""
    try:
        import psutil
    except ImportError:
        print("Warning: psutil not found, cannot wait for processes effectively.")
        time.sleep(timeout) # Fallback to simple sleep
        return

    start_wait_time = time.time()
    processes_to_watch = []
    pids_in_state = []

    if batch_key not in state_data.get("batches", {}):
        print(f"Warning: Batch key '{batch_key}' not found in provided state data for waiting.")
        return

    processes_info = state_data["batches"][batch_key].get("processes", [])
    for pinfo in processes_info:
        pid = pinfo.get("pid")
        status = pinfo.get("status")
        if pid and status == "Running": # Only wait for those marked as Running
            pids_in_state.append(pid)
            try:
                p = psutil.Process(pid)
                # Check if it's actually running before adding
                if p.is_running():
                    processes_to_watch.append(p)
            except psutil.NoSuchProcess:
                continue # Already gone
            except (psutil.AccessDenied, psutil.ZombieProcess):
                print(f"Warning: Cannot access/check PID {pid}, cannot guarantee wait.")
                continue
            except Exception as e:
                print(f"Warning: Error checking PID {pid} before wait: {e}")
                continue

    if not processes_to_watch:
        # print("No running processes found in state to wait for.")
        return

    # print(f"Waiting up to {timeout}s for PIDs: {[p.pid for p in processes_to_watch]}...")
    gone, alive = psutil.wait_procs(processes_to_watch, timeout=timeout)
    end_wait_time = time.time()
    # print(f"Wait finished in {end_wait_time - start_wait_time:.2f}s. Gone: {[p.pid for p in gone]}, Alive: {[p.pid for p in alive]}")

    if alive:
        print(f"[bold yellow]Warning:[/bold yellow] Processes still alive after {timeout}s: {[p.pid for p in alive]}")
        for p in alive:
            try:
                print(f"Terminating PID {p.pid}...")
                p.terminate() # Try gentle first
            except psutil.Error as e:
                print(f"Error terminating process {p.pid}: {e}")
        # Wait a moment after terminate
        gone_after_term, alive_after_term = psutil.wait_procs(alive, timeout=1.5) # Increase wait after terminate
        if alive_after_term:
            print(f"[bold red]Warning:[/bold red] Processes still alive after terminate: {[p.pid for p in alive_after_term]}")
            for p in alive_after_term:
                 try:
                    print(f"Killing PID {p.pid}...")
                    p.kill() # Force kill
                 except psutil.Error as e:
                    print(f"Error killing process {p.pid}: {e}")

# --- Test Cases ---

class TestAddCommand:
    def test_add_single_command(self, test_dir, batch_file):
        cmd_to_add = "echo 'Hello Batch'"
        result = run_script(["add", "--batch-file", str(batch_file), "--command", cmd_to_add], test_dir)

        assert result.returncode == 0, f"Script failed with stderr:\n{result.stderr}"
        assert batch_file.exists()
        with open(batch_file, 'r', encoding='utf-8') as f:
            content = f.read()
        assert cmd_to_add in content
        # Check rich output (might be fragile if colors change)
        assert "now contains [bold]1[/bold] command(s)" in result.stdout or "now contains 1 command(s)" in result.stdout

    def test_add_create_file_and_dir(self, test_dir):
        nested_dir = test_dir / "new_subdir"
        batch_file = nested_dir / "new_batch.cmds"
        assert not nested_dir.exists()
        result = run_script(["add", "--batch-file", str(batch_file), "-c", "echo test"], test_dir)
        assert result.returncode == 0, f"Script failed with stderr:\n{result.stderr}"
        assert nested_dir.exists()
        assert batch_file.exists()
        assert "now contains [bold]1[/bold] command(s)" in result.stdout or "now contains 1 command(s)" in result.stdout

    def test_add_append_command(self, test_dir, batch_file):
        cmd1 = "echo first"
        cmd2 = "echo second"
        run_script(["add", "--batch-file", str(batch_file), "-c", cmd1], test_dir)
        result = run_script(["add", "--batch-file", str(batch_file), "-c", cmd2], test_dir)

        assert result.returncode == 0, f"Script failed with stderr:\n{result.stderr}"
        with open(batch_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        assert len(lines) == 2
        assert lines[0].strip() == cmd1
        assert lines[1].strip() == cmd2
        assert "now contains [bold]2[/bold] command(s)" in result.stdout or "now contains 2 command(s)" in result.stdout

    def test_add_from_file(self, test_dir, batch_file):
        source_file = test_dir / "source_cmds.txt"
        cmds_in_source = ["cmd 1", "# comment", "cmd 2", "", "cmd 3"]
        with open(source_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(cmds_in_source))

        result = run_script(["add", "--batch-file", str(batch_file), "--from-file", str(source_file)], test_dir)

        assert result.returncode == 0, f"Script failed with stderr:\n{result.stderr}"
        assert batch_file.exists()
        with open(batch_file, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f if line.strip()]
        assert lines == ["cmd 1", "cmd 2", "cmd 3"] # Comments and empty lines ignored
        assert "Added 3 command(s) from" in result.stdout
        assert "now contains [bold]3[/bold] command(s)" in result.stdout or "now contains 3 command(s)" in result.stdout

    def test_add_from_file_not_found(self, test_dir, batch_file):
        source_file = test_dir / "non_existent_source.txt"
        result = run_script(["add", "--batch-file", str(batch_file), "-f", str(source_file)], test_dir)

        # Script should print error to stdout/stderr but exit 0 as the 'add' operation itself didn't fail catastrophically
        assert result.returncode == 0
        assert not batch_file.exists() # Batch file shouldn't be created if source is invalid
        # Check stdout for the rich error message
        assert f"Error:[/red] Source file '{source_file.resolve()}' not found" in result.stdout or "Error: Source file" in result.stdout

    def test_add_empty_command(self, test_dir, batch_file):
        result = run_script(["add", "--batch-file", str(batch_file), "--command", "   "], test_dir)
        assert result.returncode == 0, f"Script failed with stderr:\n{result.stderr}"
        assert "Provided command was empty" in result.stdout
        assert not batch_file.exists() # Shouldn't create file for empty command

class TestRunCommand:
    # Helper to check log content robustly
    def _check_log_contains(self, log_path: Path, expected_texts: list):
        assert log_path.exists(), f"Log file {log_path} does not exist."
        try:
            # Give a tiny bit more time for flush, especially on slower systems/CI
            time.sleep(0.1)
            content = log_path.read_text(encoding='utf-8')
            for text in expected_texts:
                assert text in content, f"Expected text '{text}' not found in log file {log_path}\n--- Log Content ---\n{content}\n-----------------"
        except Exception as e:
            pytest.fail(f"Error reading or checking log file {log_path}: {e}")

    def test_run_simple_batch(self, test_dir, batch_file, log_dir, state_file):
        # Use platform-specific commands if needed, or simple cross-platform ones
        cmd1_out = "Test Output 1"
        cmd1_err = "Test Error 1"
        # Ensure python executable path has no spaces or quote it
        py_exec_quoted = f'"{PYTHON_EXEC}"' if ' ' in PYTHON_EXEC else PYTHON_EXEC
        cmd1 = f'{py_exec_quoted} -c "import sys, time; sys.stdout.write(\'{cmd1_out}\\n\'); sys.stderr.write(\'{cmd1_err}\\n\'); sys.stdout.flush(); sys.stderr.flush(); time.sleep(0.1)"'
        cmd2_out = "Test Line 2"
        cmd2 = f"echo {cmd2_out}" # Simple echo
        batch_content = f"{cmd1}\n{cmd2}\n"
        batch_file.write_text(batch_content, encoding='utf-8')

        result = run_script(["run", "--batch-file", str(batch_file)], test_dir)

        assert result.returncode == 0, f"Script failed with stderr:\n{result.stderr}"
        assert "Batch run initiated" in result.stdout # Check for success message start
        assert log_dir.exists()
        assert state_file.exists()

        # Give processes a moment to run and write state/logs
        time.sleep(1.0) # Increased sleep

        # Check state file basic structure
        state_data = {}
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                state_data = json.load(f)
        except Exception as e:
            pytest.fail(f"Failed to read or parse state file {state_file}: {e}")

        batch_key = str(batch_file.resolve())
        assert batch_key in state_data.get("batches", {}), "Batch key not found in state"
        batch_info = state_data["batches"][batch_key]
        # Initial status should be Running, might change quickly
        assert batch_info["status"] in ["Running", "Completed", "CompletedWithErrors"]
        assert "processes" in batch_info
        assert len(batch_info["processes"]) == 2, f"Expected 2 processes in state, found {len(batch_info['processes'])}"

        pids = []
        log_files = {}
        for i, pinfo in enumerate(batch_info["processes"]):
            assert "pid" in pinfo # Check essential keys
            assert "command" in pinfo
            assert "log_path" in pinfo
            assert "status" in pinfo

            # Allow for None PID if start failed (though not expected here)
            if pinfo["pid"] is not None:
                 assert isinstance(pinfo["pid"], int)
                 pids.append(pinfo["pid"])
            assert pinfo["status"] in ["Running", "Exited", "Start Failed"] # Possible states shortly after run
            assert pinfo["command"] == batch_content.strip().split('\n')[i]
            log_path = Path(pinfo["log_path"])
            # Handle potential sanitization differences in log name check
            assert log_path.name.startswith(f"cmd_{i+1}_"), f"Log filename '{log_path.name}' doesn't start as expected."
            assert log_path.parent.resolve() == log_dir.resolve()
            log_files[i] = log_path

        # Wait for potentially running processes to finish before checking logs fully
        wait_for_processes(state_data, batch_key, timeout=5)
        time.sleep(0.5) # Extra time for logs to flush after process exit

        # Check log content
        self._check_log_contains(log_files[0], [cmd1_out, cmd1_err])
        self._check_log_contains(log_files[1], [cmd2_out])


    def test_run_empty_batch(self, test_dir, batch_file, log_dir, state_file):
        batch_file.touch() # Create empty file
        result = run_script(["run", "--batch-file", str(batch_file)], test_dir)

        assert result.returncode == 0, f"Script failed with stderr:\n{result.stderr}"
        assert "Batch file is empty or contains only comments" in result.stdout
        assert not log_dir.exists()
        assert not state_file.exists() # State file shouldn't be created for empty run

    def test_run_comments_only_batch(self, test_dir, batch_file, log_dir, state_file):
        batch_file.write_text("# A comment\n# Another comment", encoding='utf-8')
        result = run_script(["run", "--batch-file", str(batch_file)], test_dir)

        assert result.returncode == 0, f"Script failed with stderr:\n{result.stderr}"
        assert "Batch file is empty or contains only comments" in result.stdout
        assert not log_dir.exists()
        assert not state_file.exists()

    def test_run_batch_file_not_found(self, test_dir):
        non_existent_file = test_dir / "no_such_batch.cmds"
        result = run_script(["run", "--batch-file", str(non_existent_file)], test_dir)

        # Script prints error, should exit 0 as run command itself didn't crash
        assert result.returncode == 0
        assert f"Error:[/red] Batch file '{non_existent_file.resolve()}' not found" in result.stdout or "Error: Batch file" in result.stdout

    def test_run_command_not_found(self, test_dir, batch_file, log_dir, state_file):
        # Use a command that's unlikely to exist
        invalid_cmd = "this_command_should_definitely_not_exist_1234567890"
        batch_file.write_text(invalid_cmd, encoding='utf-8')

        result = run_script(["run", "--batch-file", str(batch_file)], test_dir)
        assert result.returncode == 0, f"Script failed with stderr:\n{result.stderr}"
        # Check for specific failure message
        assert "failed to start" in result.stdout or "Batch run failed" in result.stdout

        assert state_file.exists(), "State file should exist even if commands fail"
        assert log_dir.exists(), "Log directory should exist even if commands fail"

        # Check state - process should be marked as Start Failed or Exited quickly
        time.sleep(0.5) # Give state a moment
        state_data = {}
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                 state_data = json.load(f)
        except Exception as e:
             pytest.fail(f"Failed to read state file {state_file}: {e}")

        batch_key = str(batch_file.resolve())
        assert batch_key in state_data.get("batches", {})
        processes = state_data["batches"][batch_key].get("processes", [])
        assert len(processes) == 1
        proc_info = processes[0]
        # Status might be "Start Failed" or "Exited" if Popen succeeded but command failed instantly
        assert proc_info["status"] in ["Start Failed", "Exited"], f"Unexpected status: {proc_info['status']}"
        assert proc_info["command"] == invalid_cmd
        log_path = Path(proc_info["log_path"])
        assert log_path.exists()

        # Check log file for error message (shell usually prints 'command not found' or similar)
        log_content = log_path.read_text(encoding='utf-8')
        # Adjust expected error messages based on common shells
        expected_errors = ["not found", "nicht gefunden", "is not recognized", "No such file or directory", "BATCHRUNNER: Failed to start process"]
        assert any(err in log_content for err in expected_errors), f"Command not found error missing from log:\n{log_content}"

        # Status command should reflect the failure
        status_result = run_script(["status", "--batch-file", str(batch_file)], test_dir, timeout_override=5) # Short run for status check
        assert "Exited" in status_result.stdout or "Start Failed" in status_result.stdout

    def test_run_prevents_concurrent(self, test_dir, batch_file, state_file):
        """ Test that a second 'run' is prevented if the first is 'Running'. """
        cmd = "timeout /t 5 /nobreak > NUL" if sys.platform == "win32" else "sleep 5"
        batch_file.write_text(cmd, encoding='utf-8')

        # Start the first run
        result1 = run_script(["run", "--batch-file", str(batch_file)], test_dir)
        assert result1.returncode == 0, f"First run failed: {result1.stderr}"
        assert "Batch run initiated" in result1.stdout
        assert state_file.exists()
        time.sleep(0.5) # Ensure state is written and process is running

        # Attempt the second run while the first should still be active
        result2 = run_script(["run", "--batch-file", str(batch_file)], test_dir)
        assert result2.returncode == 0 # Script exits gracefully after printing error
        assert "Warning:[/yellow] Batch" in result2.stdout or "Warning: Batch" in result2.stdout # Check for the warning
        assert "seems to have running processes" in result2.stdout
        assert "Error:[/red] Cannot start a new run while another appears active" in result2.stdout or "Error: Cannot start" in result2.stdout

        # Clean up: need to stop the first run's processes
        state_data = {}
        try:
            # Need to reload state as the second run didn't modify it
            with open(state_file, 'r', encoding='utf-8') as f:
                 state_data = json.load(f)
        except Exception as e:
            print(f"Warning: Could not read state file for cleanup: {e}")
            # If state is gone, assume processes might be too, or try finding them another way if needed
            return # Cannot wait without state

        batch_key = str(batch_file.resolve())
        wait_for_processes(state_data, batch_key, timeout=6) # Wait longer than sleep + kill


class TestStatusCommand:
    @pytest.fixture(autouse=True)
    def _run_batch_first(self, test_dir, batch_file):
        """Fixture to run a simple batch before each status test."""
        py_exec_quoted = f'"{PYTHON_EXEC}"' if ' ' in PYTHON_EXEC else PYTHON_EXEC
        # Command 1: Runs for ~1 sec, prints start/end messages
        cmd1 = f'{py_exec_quoted} -c "import time, sys; sys.stdout.write(\'Proc 1 Running\\n\'); sys.stdout.flush(); time.sleep(1.0); sys.stdout.write(\'Proc 1 Done\\n\'); sys.stdout.flush()"'
        # Command 2: Sleeps briefly, then exits
        cmd2_verb = "timeout /t 1 /nobreak > NUL" if sys.platform == "win32" else "sleep 0.6" # Adjusted sleep time
        cmd2 = f"{cmd2_verb} && echo Proc 2 Done"
        batch_file.write_text(f"{cmd1}\n{cmd2}", encoding='utf-8')

        run_result = run_script(["run", "--batch-file", str(batch_file)], test_dir)
        assert run_result.returncode == 0, f"Setup for status test failed:\n{run_result.stderr}"
        time.sleep(0.4) # Give processes extra time to start and state file to be written
        # Ensure state file exists after run
        # Calculate expected state file path relative to batch file in test_dir
        state_path = batch_file.parent / ".batch_runner_state.json"
        assert state_path.exists(), f"State file {state_path} was not created by the setup run command"
        return str(batch_file.resolve()) # Return the batch key

    def _run_status_interactive(self, test_dir, batch_file, duration=1.0):
        """ Helper to run status for a duration and capture output """
        command = [PYTHON_EXEC, str(SCRIPT_PATH), "status", "--batch-file", str(batch_file)]
        stdout, stderr = "", ""
        proc = None
        try:
            # Use CREATE_NEW_PROCESS_GROUP on Win to allow sending CTRL_C_EVENT correctly
            # Use preexec_fn=os.setsid on Unix to create process group for SIGINT
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            preexec_fn = os.setsid if sys.platform != "win32" else None

            proc = subprocess.Popen(
                command, cwd=test_dir,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
                creationflags=creationflags, preexec_fn=preexec_fn
            )
            # Let status run for a short time
            proc.wait(timeout=duration) # Let it run; will raise TimeoutExpired
        except subprocess.TimeoutExpired:
            # Send signal to stop the status command (simulates Ctrl+C/q)
            try:
                if sys.platform == "win32":
                    # Send Ctrl+C to the process group on Windows - This might not always work as expected for console apps
                    # A more reliable way might be proc.terminate() or proc.kill() but doesn't test signal handler
                     os.kill(proc.pid, signal.CTRL_C_EVENT)
                else:
                    # Send SIGINT to the process group on Unix-like systems
                    # Need to get the process group ID (same as PID if setsid was used)
                     pgid = os.getpgid(proc.pid)
                     os.killpg(pgid, signal.SIGINT)
            except ProcessLookupError:
                print(f"Warning: Status process {proc.pid} already exited before signal could be sent.")
            except Exception as sig_err:
                print(f"Warning: Error sending signal to stop status process {proc.pid}: {sig_err}")
                if proc.poll() is None: proc.kill() # Fallback to kill

            # Get output after signal
            try:
                 stdout, stderr = proc.communicate(timeout=2.0) # Increased wait for termination
            except subprocess.TimeoutExpired:
                print(f"Warning: Status process {proc.pid} did not terminate after signal, killing.")
                if proc.poll() is None: proc.kill()
                stdout, stderr = proc.communicate() # Consume any remaining output
            except Exception as comm_err:
                 print(f"Warning: Error communicating with status process after signal: {comm_err}")
                 if proc and proc.poll() is None: proc.kill() # Ensure it's dead
                 # Try reading directly if communicate failed after kill
                 stdout = proc.stdout.read() if proc.stdout else ""
                 stderr = proc.stderr.read() if proc.stderr else ""

        except Exception as popen_err:
             pytest.fail(f"Failed to run status command: {popen_err}")
        finally:
             # Ensure process is terminated
             if proc and proc.poll() is None:
                 print(f"Warning: Status process {proc.pid} did not terminate gracefully, killing.")
                 proc.kill()
                 try:
                     proc.communicate(timeout=1) # Consume any remaining output
                 except: pass

        return stdout, stderr

    def test_status_running(self, test_dir, batch_file, state_file, _run_batch_first):
        batch_key = _run_batch_first
        # Run status while processes are likely still running (short duration)
        stdout, stderr = self._run_status_interactive(test_dir, batch_file, duration=0.8)

        # Check output for key elements (avoiding exact table format match)
        assert "Status for Batch" in stdout, f"Expected title not found in stdout:\n{stdout}"
        assert batch_file.name in stdout
        assert "PID" in stdout and "Command" in stdout and "Status" in stdout and "Runtime" in stdout
        # Check for at least one process likely running or sleeping based on commands
        assert ("Proc 1 Running" in stdout or "[green]Running" in stdout or "[blue]Sleeping" in stdout), f"Expected running/sleeping status not found:\n{stdout}"
        # Check stderr for unexpected errors from the status command itself
        # Allow specific warnings (like signal handler issues if not main thread) but not tracebacks
        assert "Traceback (most recent call last)" not in stderr, f"Status command produced unexpected Traceback in stderr:\n{stderr}"
        # assert "Error" not in stderr # Re-evaluate this - some expected warnings contain "Error"

        # Check state file: Overall status should be Running, at least one process Running
        if state_file.exists():
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state_data = json.load(f)
                assert batch_key in state_data.get("batches", {})
                assert state_data["batches"][batch_key]["status"] == "Running"
                process_statuses = [p.get("status") for p in state_data["batches"][batch_key].get("processes", [])]
                assert "Running" in process_statuses, f"Expected at least one process 'Running' in state, found statuses: {process_statuses}"
            except Exception as e:
                pytest.fail(f"Error reading or asserting state file content: {e}")
        else:
             pytest.fail(f"State file {state_file} was not created or disappeared during setup/run.")


    def test_status_after_completion(self, test_dir, batch_file, state_file, _run_batch_first):
        batch_key = _run_batch_first
        # Wait long enough for all processes in the fixture batch to complete
        # Longest process is ~1.0s + 0.6s, add buffer.
        print("\nWaiting for processes to complete...")
        time.sleep(2.2) # Increased wait time

        # Run status - it should detect completed processes and update state
        stdout, stderr = self._run_status_interactive(test_dir, batch_file, duration=0.8) # Short run is enough

        assert "Status for Batch" in stdout, f"Expected title not found in stdout:\n{stdout}"
        # Check that "Exited" is present for the finished processes
        assert "Exited" in stdout, f"Expected 'Exited' status not found in output:\n{stdout}"
        # Ensure no unexpected errors printed by status command
        assert "Traceback (most recent call last)" not in stderr, f"Status command produced unexpected Traceback in stderr:\n{stderr}"

        # Check state file for updated status (it might need a second non-interactive run)
        assert state_file.exists(), f"State file {state_file} does not exist"
        final_state_data = {}
        batch_info = {}
        batch_status = "Unknown"
        process_statuses = []

        # Read state after the interactive run
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                 current_state_data = json.load(f)
            batch_info = current_state_data.get("batches", {}).get(batch_key, {})
            batch_status = batch_info.get("status", "Unknown")
        except Exception as e:
             pytest.fail(f"Failed to read state file {state_file} after interactive status: {e}")

        # If status command didn't update state fully during interactive run, run it once more non-interactively
        # This handles the case where the state update write happens just as the interactive status is killed
        if batch_status == "Running":
             print("Batch status still 'Running' after interactive status check, running non-interactively to ensure update...")
             status_update_result = run_script(["status", "--batch-file", str(batch_file)], test_dir, timeout_override=3) # Short non-interactive run
             assert status_update_result.returncode == 0, f"Non-interactive status update failed: {status_update_result.stderr}"
             time.sleep(0.3) # Give a moment for potential write
             try:
                 with open(state_file, 'r', encoding='utf-8') as f:
                     final_state_data = json.load(f)
                 batch_info = final_state_data.get("batches", {}).get(batch_key, {})
                 batch_status = batch_info.get("status", "Unknown")
             except Exception as e:
                 pytest.fail(f"Failed to read state file {state_file} after non-interactive status: {e}")
        else:
             final_state_data = current_state_data # Use already updated state

        # Now assert the final state
        # Expect 'Completed' because both test commands exit cleanly (0)
        assert batch_status == "Completed", f"Final batch status is '{batch_status}', expected Completed"

        processes_info = batch_info.get("processes", [])
        assert len(processes_info) == 2, "Should still have info for 2 processes"
        all_exited = True
        for i, pinfo in enumerate(processes_info):
            final_proc_status = pinfo.get("status")
            assert final_proc_status == "Exited", f"Process {i+1} (PID {pinfo.get('pid', 'N/A')}) status is '{final_proc_status}', expected Exited"
            # Exit code for echo/sleep/timeout should be 0
            assert pinfo.get("exit_code") == 0, f"Process {i+1} (PID {pinfo.get('pid', 'N/A')}) exit code is {pinfo.get('exit_code')}, expected 0"
            assert pinfo.get("end_time") is not None, f"Process {i+1} (PID {pinfo.get('pid', 'N/A')}) end_time is None"
            start_time = pinfo.get("start_time")
            end_time = pinfo.get("end_time")
            if start_time and end_time:
                 runtime = end_time - start_time
                 assert runtime >= 0, f"Process {i+1} (PID {pinfo.get('pid', 'N/A')}) has negative runtime"
            else:
                 pytest.fail(f"Missing start or end time for process {i+1} (PID {pinfo.get('pid', 'N/A')})")


    def test_status_batch_not_found(self, test_dir, batch_file, _run_batch_first):
        # Fixture _run_batch_first creates a batch run (batch_file), but we test a *different* file
        non_existent_batch = test_dir / "no_such_batch.cmds"
        # Run status non-interactively is sufficient
        result = run_script(["status", "--batch-file", str(non_existent_batch)], test_dir, timeout_override=3)

        assert result.returncode == 0, f"Script failed with stderr:\n{result.stderr}"
        # Check stdout for the specific "not found" message
        assert f"No running or previous batch found matching key" in result.stdout
        assert f"'{non_existent_batch.name}'" in result.stdout # Check filename part
        assert "Checked state file:" in result.stdout

    def test_status_invalid_state_file(self, test_dir, batch_file, state_file, _run_batch_first):
        # Corrupt the state file created by the fixture
        assert state_file.exists(), "State file should exist from fixture run"
        state_file.write_text("{invalid json", encoding='utf-8')

        # Run status non-interactively
        result = run_script(["status", "--batch-file", str(batch_file)], test_dir, timeout_override=3)

        # The status command itself shouldn't crash; load_state handles corruption
        assert result.returncode == 0, f"Script failed with stderr:\n{result.stderr}"
        # load_state should print a warning to stderr
        assert "Warning:[/yellow] State file" in result.stderr or "Warning: State file" in result.stderr
        assert "corrupted" in result.stderr or "invalid JSON" in result.stderr
        # Since state is reset, status should report 'not found' in stdout
        assert f"No running or previous batch found matching key" in result.stdout


# Keep state file location test as it uses integration approach
class TestStateFileHandling:
    def test_state_file_location(self, test_dir):
        # Test with nested directories
        nested_dir = test_dir / "subdir1" / "subdir2"
        nested_dir.mkdir(parents=True)
        batch_file = nested_dir / "nested_batch.cmds"
        # Resolve expected paths AFTER creating directory
        state_file = nested_dir.resolve() / ".batch_runner_state.json"
        log_dir = nested_dir.resolve() / "logs"

        batch_file.write_text("echo 'hello nested'", encoding='utf-8')
        result = run_script(["run", "--batch-file", str(batch_file)], test_dir) # Run from root test dir

        assert result.returncode == 0, f"Script failed with stderr:\n{result.stderr}"
        time.sleep(0.5) # Give time for state/log creation

        assert state_file.exists(), f"State file not found at {state_file}"
        assert log_dir.exists(), f"Log directory not found at {log_dir}"
        log_files = list(log_dir.glob("*.log"))
        assert len(log_files) == 1, f"Expected 1 log file, found {len(log_files)}"

        state_data = {}
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                 state_data = json.load(f)
        except Exception as e:
            pytest.fail(f"Failed to read state file {state_file}: {e}")

        batch_key = str(batch_file.resolve())
        assert batch_key in state_data.get("batches", {}), f"Batch key {batch_key} not in state"

        # Clean up the process started by the run command
        wait_for_processes(state_data, batch_key)

# --- (End of Test Classes) ---
