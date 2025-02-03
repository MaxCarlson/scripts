import os
import datetime
import subprocess
import json
import sys
import tempfile
import pytest

# Import functions and globals from your script.
from git_sync import (
    DEBUG_ENABLED,
    _current_log_filepath,
    LOG_DIR,
    LOG_FILENAME_PREFIX,
    enable_file_logging,
    _initialize_log_file,
    debug_log,
    verbose_log,
    error_log,
    run_command,
    get_submodule_names,
    summarize_git_status_porcelain,
    handle_submodules,
    process_git_workflow,
)

# --- Fake process object that supports tuple unpacking ---
class FakeCompletedProcess:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode

    def __iter__(self):
        # Allows unpacking as (stdout, stderr, returncode)
        yield self.stdout
        yield self.stderr
        yield self.returncode

# 1. Test log file initialization
def test_initialize_log_file(monkeypatch, tmp_path):
    temp_log_dir = tmp_path / "logs"
    monkeypatch.setattr("git_sync.LOG_DIR", str(temp_log_dir))
    
    log_filepath = _initialize_log_file()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    expected_filename = f"{LOG_FILENAME_PREFIX}_{today}.log"
    assert expected_filename in log_filepath
    assert os.path.exists(os.path.dirname(log_filepath))

# 2. Test enabling file logging sets the global _current_log_filepath
def test_enable_file_logging(monkeypatch, tmp_path):
    temp_log_dir = tmp_path / "logs"
    monkeypatch.setattr("git_sync.LOG_DIR", str(temp_log_dir))
    monkeypatch.setattr("git_sync._current_log_filepath", None)
    enable_file_logging()
    current_log_filepath = getattr(__import__("git_sync"), "_current_log_filepath")
    assert current_log_filepath is not None
    assert os.path.exists(os.path.dirname(current_log_filepath))

# 3. Test debug_log writes to stdout and file
def test_debug_log(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("git_sync.DEBUG_ENABLED", True)
    temp_log_file = tmp_path / "debug.log"
    monkeypatch.setattr("git_sync._current_log_filepath", str(temp_log_file))
    message = "Test debug message"
    debug_log(message)
    captured = capsys.readouterr().out
    assert "Test debug message" in captured
    with open(str(temp_log_file), "r") as f:
        file_content = f.read()
    assert "Test debug message" in file_content

# 4. Test verbose_log writes to stdout and file
def test_verbose_log(monkeypatch, tmp_path, capsys):
    temp_log_file = tmp_path / "verbose.log"
    monkeypatch.setattr("git_sync._current_log_filepath", str(temp_log_file))
    message = "Test verbose message"
    verbose_log(message)
    captured = capsys.readouterr().out
    assert "Test verbose message" in captured
    with open(str(temp_log_file), "r") as f:
        file_content = f.read()
    assert "Test verbose message" in file_content

# 5. Test error_log writes to stderr and file
def test_error_log(monkeypatch, tmp_path, capsys):
    temp_log_file = tmp_path / "error.log"
    monkeypatch.setattr("git_sync._current_log_filepath", str(temp_log_file))
    message = "Test error message"
    error_log(message)
    captured = capsys.readouterr().err
    assert "Test error message" in captured
    with open(str(temp_log_file), "r") as f:
        file_content = f.read()
    assert "Test error message" in file_content

# 6. Test run_command for a successful command
def test_run_command_success(monkeypatch):
    def fake_run(command_list, cwd, capture_output=False, text=False, check=False, encoding=None):
        return FakeCompletedProcess(stdout="hello\n", stderr="", returncode=0)
    monkeypatch.setattr(subprocess, "run", fake_run)
    stdout, stderr, returncode = run_command(["echo", "hello"], cwd=".", capture_output=True, text=True)
    assert stdout.strip() == "hello"
    assert stderr == ""
    assert returncode == 0

# 7. Test run_command when command is not found (simulate FileNotFoundError)
def test_run_command_not_found(monkeypatch):
    def fake_run(command_list, cwd, capture_output=False, text=False, check=False, encoding=None):
        raise FileNotFoundError("Command not found")
    monkeypatch.setattr(subprocess, "run", fake_run)
    stdout, stderr, returncode = run_command(["nonexistent_cmd"], cwd=".", capture_output=True, text=True)
    assert stdout is None
    assert "Command not found" in stderr
    assert returncode == 127

# 8. Test run_command with a generic exception
def test_run_command_exception(monkeypatch):
    def fake_run(command_list, cwd, capture_output=False, text=False, check=False, encoding=None):
        raise Exception("Generic error")
    monkeypatch.setattr(subprocess, "run", fake_run)
    stdout, stderr, returncode = run_command(["cmd"], cwd=".", capture_output=True, text=True)
    assert stdout is None
    assert "Generic error" in stderr
    assert returncode == 1

# 9. Test get_submodule_names using a fake subprocess output
def test_get_submodule_names(monkeypatch):
    fake_output = " 3d2f4e0 submodule1 (heads/master)\n-abcdef0 submodule2 (remotes/origin/feature)\n"
    monkeypatch.setattr("git_sync.run_command", lambda *args, **kwargs: (fake_output, "", 0))
    submodules = get_submodule_names("dummy_repo")
    assert "submodule1" in submodules
    assert "submodule2" in submodules

# 10. Test summarize_git_status_porcelain with sample input
def test_summarize_git_status_porcelain():
    empty_status = ""
    summary = summarize_git_status_porcelain(empty_status)
    assert summary == "No changes."
    
    status_input = "M  file1.txt\nA  file2.txt\n?? file3.txt\n"
    summary = summarize_git_status_porcelain(status_input)
    assert "Modified files:" in summary
    assert "M file1.txt" in summary
    assert "A file2.txt" in summary
    assert "Untracked files:" in summary
    assert "? file3.txt" in summary

# 11. Test handle_submodules by simulating a repository with one submodule.
def test_handle_submodules(monkeypatch, capsys):
    fake_submodules = " 1111111 submodule_test (heads/main)\n"
    called_commands = []

    def fake_run(command_list, cwd, capture_output=False, text=False, verbose=False, **kwargs):
        called_commands.append((command_list, cwd))
        if "submodule" in command_list and "status" in command_list:
            return FakeCompletedProcess(stdout=fake_submodules, stderr="", returncode=0)
        return FakeCompletedProcess(stdout="", stderr="", returncode=0)

    monkeypatch.setattr("git_sync.run_command", fake_run)
    repo_path = "dummy_repo"
    add_pattern = "."
    force = False
    branch = "main"
    submodules_to_process = "all"
    submodule_add_patterns = {}
    submodule_branches = {}
    handle_submodules(repo_path, add_pattern, force, branch,
                      submodules_to_process, submodule_add_patterns,
                      submodule_branches, verbose=True)
    init_found = any("submodule" in cmd[0] and "init" in cmd[0] for cmd in called_commands)
    update_found = any("submodule" in cmd[0] and "update" in cmd[0] for cmd in called_commands)
    assert init_found, "Expected a git submodule init command"
    assert update_found, "Expected a git submodule update command"

# 12. Test process_git_workflow for the case with no changes.
def test_process_git_workflow_no_changes(monkeypatch, capsys):
    def fake_run(command_list, cwd, capture_output=False, text=False, verbose=False, **kwargs):
        if "status" in command_list and "--porcelain" in command_list:
            return FakeCompletedProcess(stdout="", stderr="", returncode=0)
        if "status" in command_list and "--color=always" in command_list:
            return FakeCompletedProcess(stdout="On branch main\n", stderr="", returncode=0)
        return FakeCompletedProcess(stdout="", stderr="", returncode=0)
    monkeypatch.setattr("git_sync.run_command", lambda *args, **kwargs: fake_run(*args, **kwargs))
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    process_git_workflow(add_pattern=".", force=False, cwd="dummy_repo", branch="main",
                           submodules_to_process=None, submodule_add_patterns={}, submodule_branches={}, verbose=True)
    captured = capsys.readouterr().out
    assert "No changes to commit." in captured

# 13. Test process_git_workflow with a simulated change and commit flow.
def test_process_git_workflow_with_changes(monkeypatch, capsys):
    def fake_run(command_list, cwd, capture_output=False, text=False, verbose=False, **kwargs):
        cmd_str = " ".join(command_list)
        if "status --porcelain" in cmd_str:
            return FakeCompletedProcess(stdout="M  file.txt\n", stderr="", returncode=0)
        if "add --dry-run" in cmd_str:
            return FakeCompletedProcess(stdout="file.txt\n", stderr="", returncode=0)
        if "add " in cmd_str:
            return FakeCompletedProcess(stdout="", stderr="", returncode=0)
        if "commit" in cmd_str:
            return FakeCompletedProcess(stdout="Committed\n", stderr="", returncode=0)
        if "pull" in cmd_str:
            return FakeCompletedProcess(stdout="Pulled\n", stderr="", returncode=0)
        if "push" in cmd_str:
            return FakeCompletedProcess(stdout="Pushed\n", stderr="", returncode=0)
        return FakeCompletedProcess(stdout="", stderr="", returncode=0)
    monkeypatch.setattr("git_sync.run_command", fake_run)
    inputs = iter(["y", "Test commit message"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    process_git_workflow(add_pattern=".", force=False, cwd="dummy_repo", branch="main",
                           submodules_to_process=None, submodule_add_patterns={}, submodule_branches={}, verbose=True)
    captured = capsys.readouterr().out
    assert "Changes to be staged if you continue:" in captured or "No changes to stage" in captured
    assert "Committed" in captured

# 14. Test process_git_workflow with multiple submodules and recursion.
def test_process_git_workflow_multiple_submodules(monkeypatch, capsys):
    call_history = []

    def fake_run(command_list, cwd, capture_output=False, text=False, verbose=False, **kwargs):
        cmd_str = " ".join(command_list)
        call_history.append((cmd_str, cwd))
        if "git submodule status" in cmd_str:
            if cwd == "dummy_repo":
                return FakeCompletedProcess(stdout=" 1111111 sub1 (heads/main)\n2222222 sub2 (heads/main)\n", stderr="", returncode=0)
            elif cwd == os.path.join("dummy_repo", "sub1"):
                return FakeCompletedProcess(stdout=" 3333333 sub1a (heads/main)\n", stderr="", returncode=0)
            else:
                return FakeCompletedProcess(stdout="", stderr="", returncode=0)
        if "--porcelain" in cmd_str:
            return FakeCompletedProcess(stdout="M  file.txt\n", stderr="", returncode=0)
        if "add --dry-run" in cmd_str:
            return FakeCompletedProcess(stdout="file.txt\n", stderr="", returncode=0)
        if "add " in cmd_str:
            return FakeCompletedProcess(stdout="", stderr="", returncode=0)
        if "commit" in cmd_str:
            return FakeCompletedProcess(stdout="Committed\n", stderr="", returncode=0)
        if "pull" in cmd_str:
            return FakeCompletedProcess(stdout="Pulled\n", stderr="", returncode=0)
        if "push" in cmd_str:
            return FakeCompletedProcess(stdout="Pushed\n", stderr="", returncode=0)
        return FakeCompletedProcess(stdout="", stderr="", returncode=0)

    monkeypatch.setattr("git_sync.run_command", fake_run)
    inputs = iter(["y", "Main commit message", "y", "Sub1 commit message", "y", "Sub1a commit message", "y", "Sub2 commit message"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    process_git_workflow(add_pattern=".", force=False, cwd="dummy_repo", branch="main",
                           submodules_to_process="all", submodule_add_patterns={}, submodule_branches={}, verbose=True)
    captured = capsys.readouterr().out
    sub1_present = any("sub1" in cwd for (cmd, cwd) in call_history)
    sub2_present = any("sub2" in cwd for (cmd, cwd) in call_history)
    sub1a_present = any("sub1a" in cwd for (cmd, cwd) in call_history)
    assert sub1_present, "Expected commands to run in sub1"
    assert sub2_present, "Expected commands to run in sub2"
    assert sub1a_present, "Expected commands to run in sub1a (nested submodule)"

