import pytest
import subprocess
import sys
import os
import time
import json
from pathlib import Path
import shutil
import signal

# Assume batch_runner.py is in the same directory or accessible in PATH
SCRIPT_NAME = "batch_runner.py"
PYTHON_EXEC = sys.executable # Use the same python interpreter running pytest

# --- Fixtures ---

@pytest.fixture(scope="function")
def test_dir(tmp_path):
    """Provides a temporary directory for each test function."""
    # tmp_path is a Path object provided by pytest
    yield tmp_path
    # Cleanup happens automatically when tmp_path goes out of scope


@pytest.fixture(scope="function")
def batch_file(test_dir):
    """Provides the path to a batch file within the test directory."""
    return test_dir / "test_batch.cmds"

@pytest.fixture(scope="function")
def state_file(batch_file):
    """Provides the expected path to the state file."""
    return batch_file.parent / ".batch_runner_state.json"

@pytest.fixture(scope="function")
def log_dir(batch_file):
    """Provides the expected path to the log directory."""
    return batch_file.parent / "logs"

# --- Helper Function ---

def run_script(args: list, cwd: Path) -> subprocess.CompletedProcess:
    """Runs the batch_runner.py script with given arguments."""
    command = [PYTHON_EXEC, SCRIPT_NAME] + args
    # Setting a timeout is crucial to prevent tests hanging indefinitely
    # Extend if testing longer-running commands, but keep it reasonable
    timeout_seconds = 10
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=cwd, # Run the script relative to the test directory
            check=False, # Don't raise exception on non-zero exit code
            timeout=timeout_seconds
        )
        return result
    except subprocess.TimeoutExpired as e:
        print(f"Timeout expired running: {' '.join(command)}")
        print(f"Stdout: {e.stdout}")
        print(f"Stderr: {e.stderr}")
        pytest.fail(f"Script timed out after {timeout_seconds}s: {' '.join(command)}")


def wait_for_processes(state_data: dict, batch_key: str, timeout: int = 5):
    """Waits for processes listed in the state file to finish."""
    import psutil # Import locally as it's only needed here
    start_time = time.time()
    processes_to_watch = []
    if batch_key in state_data.get("batches", {}):
         processes_info = state_data["batches"][batch_key].get("processes", [])
         for pinfo in processes_info:
             pid = pinfo.get("pid")
             if pid:
                 try:
                     p = psutil.Process(pid)
                     processes_to_watch.append(p)
                 except psutil.NoSuchProcess:
                     continue # Already gone

    gone, alive = psutil.wait_procs(processes_to_watch, timeout=timeout)
    if alive:
        print(f"Warning: Processes still alive after {timeout}s: {[p.pid for p in alive]}")
        # Force kill remaining processes to prevent test interference
        for p in alive:
            try:
                p.terminate() # Try gentle first
                time.sleep(0.1)
                if p.is_running():
                    p.kill() # Force kill
            except psutil.NoSuchProcess:
                continue # Gone between check and kill
            except Exception as e:
                print(f"Error terminating/killing process {p.pid}: {e}")


# --- Test Cases ---

class TestAddCommand:
    def test_add_single_command(self, test_dir, batch_file):
        cmd_to_add = "echo 'Hello Batch'"
        result = run_script(["add", "--batch-file", str(batch_file), "--command", cmd_to_add], test_dir)

        assert result.returncode == 0
        assert batch_file.exists()
        with open(batch_file, 'r') as f:
            content = f.read()
        assert cmd_to_add in content
        assert f"now contains [bold]1[/bold] command(s)" in result.stdout # Check count output

    def test_add_create_file(self, test_dir, batch_file):
        assert not batch_file.exists()
        result = run_script(["add", "--batch-file", str(batch_file), "-c", "ls"], test_dir)
        assert result.returncode == 0
        assert batch_file.exists()
        assert "now contains [bold]1[/bold] command(s)" in result.stdout

    def test_add_append_command(self, test_dir, batch_file):
        cmd1 = "echo first"
        cmd2 = "echo second"
        run_script(["add", "--batch-file", str(batch_file), "-c", cmd1], test_dir)
        result = run_script(["add", "--batch-file", str(batch_file), "-c", cmd2], test_dir)

        assert result.returncode == 0
        with open(batch_file, 'r') as f:
            lines = f.readlines()
        assert len(lines) == 2
        assert lines[0].strip() == cmd1
        assert lines[1].strip() == cmd2
        assert f"now contains [bold]2[/bold] command(s)" in result.stdout

    def test_add_from_file(self, test_dir, batch_file):
        source_file = test_dir / "source_cmds.txt"
        cmds_in_source = ["cmd 1", "# comment", "cmd 2", "", "cmd 3"]
        with open(source_file, 'w') as f:
            f.write("\n".join(cmds_in_source))

        result = run_script(["add", "--batch-file", str(batch_file), "--from-file", str(source_file)], test_dir)

        assert result.returncode == 0
        assert batch_file.exists()
        with open(batch_file, 'r') as f:
            lines = [line.strip() for line in f if line.strip()]
        assert lines == ["cmd 1", "cmd 2", "cmd 3"] # Comments and empty lines ignored
        assert f"Added 3 command(s) from" in result.stdout
        assert f"now contains [bold]3[/bold] command(s)" in result.stdout

    def test_add_from_file_not_found(self, test_dir, batch_file):
        source_file = test_dir / "non_existent_source.txt"
        result = run_script(["add", "--batch-file", str(batch_file), "-f", str(source_file)], test_dir)

        assert result.returncode == 0 # Script doesn't exit with error code here, prints error
        assert not batch_file.exists() # Batch file shouldn't be created if source is invalid
        assert f"Error:[/red] Source file '{source_file}' not found" in result.stdout


class TestRunCommand:
    def test_run_simple_batch(self, test_dir, batch_file, log_dir, state_file):
        cmd1 = f"{PYTHON_EXEC} -c \"import sys; sys.stdout.write('out1'); sys.stderr.write('err1');\""
        cmd2 = "echo 'line2'"
        batch_content = f"{cmd1}\n{cmd2}\n"
        batch_file.write_text(batch_content)

        result = run_script(["run", "--batch-file", str(batch_file)], test_dir)

        assert result.returncode == 0
        assert "Batch run initiated successfully" in result.stdout
        assert log_dir.exists()
        assert state_file.exists()

        # Check state file basic structure
        with open(state_file, 'r') as f:
            state_data = json.load(f)

        batch_key = str(batch_file.resolve())
        assert batch_key in state_data["batches"]
        batch_info = state_data["batches"][batch_key]
        assert batch_info["status"] == "Running" # Initially marked as running
        assert len(batch_info["processes"]) == 2

        pids = []
        log_files = []
        for i, pinfo in enumerate(batch_info["processes"]):
            assert isinstance(pinfo["pid"], int)
            assert pinfo["status"] == "Running"
            assert pinfo["start_time"] is not None
            assert pinfo["exit_code"] is None
            assert pinfo["end_time"] is None
            assert pinfo["command"] == batch_content.strip().split('\n')[i]
            log_path = Path(pinfo["log_path"])
            assert log_path.name.startswith(f"cmd_{i+1}_")
            assert log_path.parent == log_dir
            assert log_path.exists() # Log file should be created
            pids.append(pinfo["pid"])
            log_files.append(log_path)

        # Wait for short processes to finish
        wait_for_processes(state_data, batch_key)
        time.sleep(0.5) # Give a little extra time for logs to flush

        # Check log content
        log1_content = log_files[0].read_text()
        log2_content = log_files[1].read_text()

        assert "out1" in log1_content
        assert "err1" in log1_content # Stderr redirected
        # Echo might add a newline depending on OS/shell
        assert "line2" in log2_content.strip()

    def test_run_empty_batch(self, test_dir, batch_file, log_dir, state_file):
        batch_file.touch() # Create empty file
        result = run_script(["run", "--batch-file", str(batch_file)], test_dir)

        assert result.returncode == 0
        assert "Batch file is empty or contains only comments" in result.stdout
        assert not log_dir.exists()
        assert not state_file.exists() # State file shouldn't be created for empty run

    def test_run_comments_only_batch(self, test_dir, batch_file, log_dir, state_file):
        batch_file.write_text("# A comment\n# Another comment")
        result = run_script(["run", "--batch-file", str(batch_file)], test_dir)

        assert result.returncode == 0
        assert "Batch file is empty or contains only comments" in result.stdout
        assert not log_dir.exists()
        assert not state_file.exists()

    def test_run_batch_file_not_found(self, test_dir, batch_file):
        result = run_script(["run", "--batch-file", str(batch_file)], test_dir)

        assert result.returncode == 0 # Script prints error, doesn't exit non-zero
        assert f"Error:[/red] Batch file '{batch_file.resolve()}' not found." in result.stdout

    def test_run_command_not_found(self, test_dir, batch_file, log_dir, state_file):
        # Use a command that's unlikely to exist
        invalid_cmd = "this_command_should_definitely_not_exist_qwertyuiop"
        batch_file.write_text(invalid_cmd)

        result = run_script(["run", "--batch-file", str(batch_file)], test_dir)
        assert result.returncode == 0 # run itself succeeds in starting the *attempt*

        assert state_file.exists()
        assert log_dir.exists()

        # Check state - process was created but likely failed quickly
        with open(state_file, 'r') as f:
             state_data = json.load(f)
        batch_key = str(batch_file.resolve())
        assert len(state_data["batches"][batch_key]["processes"]) == 1
        proc_info = state_data["batches"][batch_key]["processes"][0]
        log_path = Path(proc_info["log_path"])
        assert log_path.exists()

        # Wait briefly
        wait_for_processes(state_data, batch_key, timeout=2)
        time.sleep(0.5)

        # Check log file for error message (shell usually prints 'command not found')
        log_content = log_path.read_text()
        assert "not found" in log_content or "nicht gefunden" in log_content or "No such file or directory" in log_content # Linux/macOS/Windows variations

        # Status should eventually reflect failure
        status_result = run_script(["status", "--batch-file", str(batch_file)], test_dir)
        # Reload state after status command (which should update it)
        with open(state_file, 'r') as f:
             updated_state_data = json.load(f)
        updated_proc_info = updated_state_data["batches"][batch_key]["processes"][0]
        assert updated_proc_info["status"] == "Exited"
        assert updated_proc_info["exit_code"] is not None
        assert updated_proc_info["exit_code"] != 0 # Should be non-zero exit code


class TestStatusCommand:
    @pytest.fixture(autouse=True) # Automatically use this fixture for all tests in this class
    def _run_batch_first(self, test_dir, batch_file):
        """Fixture to run a simple batch before each status test."""
        # Use commands that finish relatively quickly but not instantly
        cmd1 = f"{PYTHON_EXEC} -c \"import time; print('Proc 1 Running'); time.sleep(0.5); print('Proc 1 Done')\""
        cmd2 = "sleep 0.2 && echo 'Proc 2 Done'"
        batch_file.write_text(f"{cmd1}\n{cmd2}")
        run_script(["run", "--batch-file", str(batch_file)], test_dir)
        # Give processes time to start
        time.sleep(0.2)
        # Return the key needed to access state
        return str(batch_file.resolve())

    def test_status_running(self, test_dir, batch_file, state_file, _run_batch_first):
        batch_key = _run_batch_first
        # Run status while processes are likely still running
        # Use timeout and SIGINT to simulate 'q' press, as mocking readchar is complex here
        command = [PYTHON_EXEC, SCRIPT_NAME, "status", "--batch-file", str(batch_file)]
        proc = subprocess.Popen(command, cwd=test_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            # Let status run for a short time
            stdout, stderr = proc.communicate(timeout=1.5)
        except subprocess.TimeoutExpired:
            # Send Ctrl+C equivalent to stop it
            proc.send_signal(signal.SIGINT)
            stdout, stderr = proc.communicate() # Get output after signal

        # Check if the output contains expected elements (less fragile than exact table)
        assert "Status for Batch" in stdout
        assert batch_file.name in stdout
        assert "PID" in stdout and "Command" in stdout and "Status" in stdout and "Runtime" in stdout
        assert "Proc 1 Running" in stdout or "sleep 0.2" in stdout # Check command names
        assert "[green]Running" in stdout or "[blue]Sleeping" in stdout # Check status colors/text

        # Check that state file wasn't drastically changed (processes still running)
        with open(state_file, 'r') as f:
             state_data = json.load(f)
        assert state_data["batches"][batch_key]["status"] == "Running" # Overall batch status
        assert state_data["batches"][batch_key]["processes"][0]["status"] == "Running"


    def test_status_after_completion(self, test_dir, batch_file, state_file, _run_batch_first):
        batch_key = _run_batch_first
        # Wait long enough for processes to complete
        time.sleep(1.0) # Wait longer than the sleeps in the commands

        # Run status - it should detect completed processes and update the state
        command = [PYTHON_EXEC, SCRIPT_NAME, "status", "--batch-file", str(batch_file)]
        proc = subprocess.Popen(command, cwd=test_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            stdout, stderr = proc.communicate(timeout=1.5) # Should exit quickly if 'q' isn't pressed
        except subprocess.TimeoutExpired:
            proc.send_signal(signal.SIGINT)
            stdout, stderr = proc.communicate()

        assert "Status for Batch" in stdout
        assert "Exited" in stdout # Should show exited status

        # Crucially, check if the state file was updated
        with open(state_file, 'r') as f:
             state_data = json.load(f)

        assert state_data["batches"][batch_key]["status"] == "Completed" # Overall status updated
        all_exited = True
        for pinfo in state_data["batches"][batch_key]["processes"]:
            assert pinfo["status"] == "Exited"
            assert pinfo["exit_code"] == 0 # Assuming clean exits for these test commands
            assert pinfo["end_time"] is not None
            runtime = pinfo["end_time"] - pinfo["start_time"]
            assert runtime > 0 # Runtime should be positive
            if pinfo["status"] != "Exited":
                all_exited = False

        assert all_exited

    def test_status_batch_not_found(self, test_dir, batch_file):
        # Don't run the batch first, just try status on a non-existent run
        non_existent_batch = test_dir / "no_such_batch.cmds"
        result = run_script(["status", "--batch-file", str(non_existent_batch)], test_dir)

        assert result.returncode == 0
        assert f"No running or previous batch found for '{non_existent_batch.resolve()}'" in result.stdout
        assert "Checked state file:" in result.stdout

    def test_status_invalid_state_file(self, test_dir, batch_file, state_file):
        # Create a corrupted state file
        state_file.write_text("{invalid json")
        # Create a dummy batch file so the script tries to find state
        batch_file.touch()

        result = run_script(["status", "--batch-file", str(batch_file)], test_dir)
        # The status command itself shouldn't crash, load_state handles corruption
        assert result.returncode == 0
        # load_state should print a warning
        # Note: Capturing rich's stderr output reliably can sometimes be tricky.
        # We check stdout for the expected "not found" message resulting from the reset state.
        assert f"No running or previous batch found for '{batch_file.resolve()}'" in result.stdout
        # Check stderr for the warning (may vary slightly based on rich version)
        assert "Warning:[/yellow] State file" in result.stderr
        assert "corrupted. Initializing new state." in result.stderr


class TestHelpers:
    def test_sanitize_filename(self):
        # Import the function directly for unit testing
        from batch_runner import sanitize_filename
        assert sanitize_filename("cmd /c echo") == "cmd__c_echo"
        assert sanitize_filename("my_script.py") == "my_script.py"
        assert sanitize_filename("a*b?c<d>e|f:g\"h") == "a_b_c_d_e_f_g_h"
        long_name = "a" * 150
        assert len(sanitize_filename(long_name)) == 100
        assert sanitize_filename("  leading spaces  ") == "__leading_spaces__"

    def test_format_duration(self):
        from batch_runner import format_duration
        assert format_duration(5) == "0:00:05"
        assert format_duration(65) == "0:01:05"
        assert format_duration(3661) == "1:01:01"
        assert format_duration(0) == "0:00:00"
        assert format_duration(-1) == "N/A"
        assert format_duration(86400 + 3600 + 60 + 1) == "1 day, 1:01:01"

    def test_format_bytes(self):
        from batch_runner import format_bytes
        assert format_bytes(100) == "100 B"
        assert format_bytes(1024) == "1.0 KB"
        assert format_bytes(1500) == "1.5 KB"
        assert format_bytes(1024*1024) == "1.0 MB"
        assert format_bytes(1024*1024*1.5) == "1.5 MB"
        assert format_bytes(1024*1024*1024*2.3) == "2.3 GB"
        assert format_bytes(None) == "N/A"

class TestStateFileHandling:
    def test_state_file_location(self, test_dir):
        # Test with nested directories
        nested_dir = test_dir / "subdir1" / "subdir2"
        nested_dir.mkdir(parents=True)
        batch_file = nested_dir / "nested_batch.cmds"
        state_file = nested_dir / ".batch_runner_state.json"
        log_dir = nested_dir / "logs"

        batch_file.write_text("echo 'hello nested'")
        result = run_script(["run", "--batch-file", str(batch_file)], test_dir) # Run from root test dir

        assert result.returncode == 0
        assert state_file.exists()
        assert log_dir.exists()
        assert len(list(log_dir.glob("*.log"))) == 1

        with open(state_file, 'r') as f:
             state_data = json.load(f)
        batch_key = str(batch_file.resolve())
        assert batch_key in state_data["batches"]

        # Clean up to avoid interference if tests run in parallel within tmp_path
        wait_for_processes(state_data, batch_key)


    def test_load_state_no_file(self, test_dir, state_file):
        from batch_runner import load_state, STATE_LOCK_FILENAME
        import filelock
        lock_path = state_file.parent / STATE_LOCK_FILENAME
        lock = filelock.FileLock(lock_path)

        assert not state_file.exists()
        state = load_state(state_file, lock)
        assert state == {"batches": {}}

    def test_save_load_state_roundtrip(self, test_dir, state_file):
        from batch_runner import load_state, save_state, STATE_LOCK_FILENAME
        import filelock
        lock_path = state_file.parent / STATE_LOCK_FILENAME
        lock = filelock.FileLock(lock_path)

        test_data = {
            "batches": {
                "/path/to/batch1.cmds": {"status": "Running", "processes": [{"pid": 123}]},
                "/path/to/batch2.cmds": {"status": "Completed", "processes": []}
            }
        }
        save_state(state_file, lock, test_data)
        assert state_file.exists()

        loaded_state = load_state(state_file, lock)
        assert loaded_state == test_data
