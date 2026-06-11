from pathlib import Path

from agent_sync.cli import main


def test_prompt_command_renders_without_external_call(tmp_path: Path, capsys) -> None:
    result = main(["-r", str(tmp_path), "prompt", "-k", "summarize", "-p", "hello"])
    captured = capsys.readouterr()
    assert result == 0
    assert "Planned worker:" in captured.out
    assert "hello" in captured.out


def test_workers_command_uses_defaults(tmp_path: Path, capsys) -> None:
    result = main(["-r", str(tmp_path), "workers", "-a"])
    captured = capsys.readouterr()
    assert result == 0
    assert "local-lmstudio" in captured.out


def test_delegate_without_allow_external_prints_policy(tmp_path: Path, capsys) -> None:
    result = main(["-r", str(tmp_path), "delegate", "-k", "summarize", "-p", "hello"])
    captured = capsys.readouterr()
    assert result == 0
    assert "Policy:" in captured.out
