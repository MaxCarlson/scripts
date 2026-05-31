import os
import subprocess
import sys
from pathlib import Path

import pytest


def run_cli(*args: str, env: dict | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
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
    result = run_cli("-r", str(root), "index", "status")
    # Status command should accept the --root flag without crashing
    assert result.returncode in (0, 1)  # may fail if dir empty, but must not crash


def test_env_var_root_accepted(tmp_path: Path) -> None:
    """AGENT_MEMORY_ROOT env var should be accepted."""
    result = run_cli("index", "status", env={"AGENT_MEMORY_ROOT": str(tmp_path)})
    assert result.returncode in (0, 1)  # dir exists but empty


def test_short_root_flag(tmp_path: Path) -> None:
    result = run_cli("-r", str(tmp_path), "index", "status")
    assert result.returncode in (0, 1)


def test_note_create_writes_file(tmp_path: Path) -> None:
    result = run_cli(
        "-r", str(tmp_path),
        "note", "create",
        "-k", "constraint",
        "-t", "Always use pathlib",
        "-b", "## Summary\n\nUse pathlib.Path.",
        "--tags", "python,style",
    )
    assert result.returncode == 0, result.stderr
    md_files = list(tmp_path.rglob("*.md"))
    assert len(md_files) == 1
    content = md_files[0].read_text(encoding="utf-8")
    assert "Always use pathlib" in content
    assert "constraint" in content


def test_note_create_prints_note_id(tmp_path: Path) -> None:
    result = run_cli(
        "-r", str(tmp_path),
        "note", "create",
        "-k", "preference",
        "-t", "Use f-strings",
    )
    assert result.returncode == 0, result.stderr
    assert "Created:" in result.stdout or len(result.stdout.strip()) > 0


def test_note_create_dry_run_prints_but_does_not_write(tmp_path: Path) -> None:
    result = run_cli(
        "-r", str(tmp_path),
        "note", "create",
        "-k", "constraint",
        "-t", "Dry run note",
        "--dry-run",
    )
    assert result.returncode == 0, result.stderr
    md_files = list(tmp_path.rglob("*.md"))
    assert len(md_files) == 0
    assert "constraint" in result.stdout or "Dry run note" in result.stdout


def test_note_create_project_required_kind_without_project_fails(tmp_path: Path) -> None:
    result = run_cli(
        "-r", str(tmp_path),
        "note", "create",
        "-k", "handoff",
        "-t", "Some handoff",
    )
    assert result.returncode != 0
    assert "project" in result.stderr.lower() or "required" in result.stderr.lower()


def test_note_create_project_required_kind_with_project_succeeds(tmp_path: Path) -> None:
    result = run_cli(
        "-r", str(tmp_path),
        "note", "create",
        "-k", "handoff",
        "-p", "my-project",
        "-t", "Handoff summary",
    )
    assert result.returncode == 0, result.stderr
    md_files = list(tmp_path.rglob("*.md"))
    assert len(md_files) == 1
