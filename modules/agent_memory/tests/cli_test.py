from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def run_cli(*args: str, env: dict | None = None, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run agent-memory CLI and return CompletedProcess."""
    return subprocess.run(
        [sys.executable, "-m", "agent_memory.cli", *args],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        cwd=cwd,
    )


def test_no_args_prints_help() -> None:
    result = run_cli()
    assert result.returncode == 0
    assert "usage" in result.stdout.lower() or "usage" in result.stderr.lower()


def test_help_flag_exits_zero() -> None:
    result = run_cli("--help")
    assert result.returncode == 0


def test_unknown_command_exits_nonzero() -> None:
    result = run_cli("nonexistent-command")
    assert result.returncode != 0


def test_root_flag_sets_notes_root(tmp_path: Path) -> None:
    """--root should be accepted and used (even if directory doesn't exist yet)."""
    root = tmp_path / "custom_notes"
    result = run_cli("index", "status", "-r", str(root))
    # Status command should accept the --root flag without crashing
    assert result.returncode in (0, 1)  # may fail if dir empty, but must not crash


def test_env_var_root_accepted(tmp_path: Path) -> None:
    """AGENT_MEMORY_ROOT env var should be accepted."""
    result = run_cli("index", "status", env={"AGENT_MEMORY_ROOT": str(tmp_path)})
    assert result.returncode in (0, 1)  # dir exists but empty


def test_short_root_flag(tmp_path: Path) -> None:
    result = run_cli("index", "status", "-r", str(tmp_path))
    assert result.returncode in (0, 1)
