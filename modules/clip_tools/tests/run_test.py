# File: pyprjs/clip_tools/tests/test_run.py
import subprocess
from types import SimpleNamespace
import clip_tools.cli as cli

class FakeCompleted:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode

class FakeHistory:
    def __init__(self, mapping):
        # mapping: n -> command string
        self.mapping = mapping
        self.shell_type = "zsh"
    def get_nth_recent_command(self, n: int):
        return self.mapping.get(n)

def test_run_direct_raw(monkeypatch, fake_sysapi, ns, capsys):
    def fake_run(cmd, shell, capture_output, text, check):
        assert "echo raw" in cmd
        return FakeCompleted(stdout="OUT\n", stderr="ERR\n", returncode=0)
    monkeypatch.setattr(subprocess, "run", fake_run)
    args = ns(replay_history=None, wrap=False, no_stats=False, command_and_args=["echo", "raw"])
    rc = cli.cmd_run(args, fake_sysapi)
    assert rc == 0
    cb = fake_sysapi.get_clipboard()
    assert "OUT" in cb and "ERR" in cb  # combined
    out = capsys.readouterr()
    assert "run stats" in out.err

def test_run_direct_wrap(monkeypatch, fake_sysapi, ns):
    def fake_run(cmd, shell, capture_output, text, check):
        return FakeCompleted(stdout="A", stderr="", returncode=0)
    monkeypatch.setattr(subprocess, "run", fake_run)
    args = ns(replay_history=None, wrap=True, no_stats=True, command_and_args=["echo", "wrapped"])
    rc = cli.cmd_run(args, fake_sysapi)
    assert rc == 0
    assert fake_sysapi.get_clipboard().startswith("$ echo")

def test_run_nonzero_exit_warns(monkeypatch, fake_sysapi, ns, capsys):
    def fake_run(cmd, shell, capture_output, text, check):
        return FakeCompleted(stdout="ok", stderr="bad", returncode=3)
    monkeypatch.setattr(subprocess, "run", fake_run)
    args = ns(replay_history=None, wrap=False, no_stats=False, command_and_args=["echo", "x"])
    rc = cli.cmd_run(args, fake_sysapi)
    assert rc == 0  # still succeeds copying output
    out = capsys.readouterr()
    assert "exited with status 3" in out.err

def test_run_default_replay_history_confirm_yes(monkeypatch, fake_sysapi, ns, capsys):
    # Patch HistoryUtilsAdapter used inside cmd_run
    monkeypatch.setattr(cli, "HistoryUtilsAdapter", lambda: FakeHistory({1: "echo hi"}))
    # Simulate user confirming
    monkeypatch.setattr(cli.console_err, "input", lambda prompt: "y")
    # Patch subprocess.run
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeCompleted(stdout="hello\n", stderr="", returncode=0))

    # No command_and_args, no -r => defaults to N=1 replay
    args = ns(replay_history=None, wrap=False, no_stats=False, command_and_args=None)
    rc = cli.cmd_run(args, fake_sysapi)
    assert rc == 0
    assert "hello" in fake_sysapi.get_clipboard()
    out = capsys.readouterr()
    assert "Replay History (N=1)" in out.err

def test_run_loop_prevention(monkeypatch, fake_sysapi, ns, capsys):
    # Simulate history command that would call this script itself
    script_name = "clip-tools"
    monkeypatch.setattr(cli, "HistoryUtilsAdapter", lambda: FakeHistory({1: script_name}))
    monkeypatch.setattr(cli.console_err, "input", lambda prompt: "y")  # confirmation won't be reached
    args = ns(replay_history=None, wrap=False, no_stats=False, command_and_args=None)
    rc = cli.cmd_run(args, fake_sysapi)
    assert rc == 1
    out = capsys.readouterr()
    assert "Loop detected" in (out.err + out.out)
