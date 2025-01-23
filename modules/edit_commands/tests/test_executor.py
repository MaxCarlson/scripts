import pytest
from edit_commands.executor import execute_command

def test_dry_run_execution(capsys):
    execute_command("echo test", dry_run=True)
    captured = capsys.readouterr()
    assert "Executing: echo test" in captured.out
