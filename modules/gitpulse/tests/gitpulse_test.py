"""Tests for GitPulse helper utilities."""

from __future__ import annotations

from typing import Sequence

import pytest

from gitpulse.cli import (
    GitPulseError,
    build_default_commit_message,
    run_combo_commands,
    show_diff_from_history,
)


class DummyRunner:
    """Test double that records git commands invoked."""

    def __init__(self) -> None:
        self.commands: list[Sequence[str]] = []

    def run(self, git_args: Sequence[str], *, capture_output: bool = False):
        self.commands.append(tuple(git_args))
        return None


def test_build_default_commit_message_counts_files() -> None:
    status_output = "M  README.md\nA  new_file.py\nD  old_file.txt\n"
    message = build_default_commit_message(status_output)
    assert message == "Modify/Add/Remove 3 files"


def test_show_diff_from_history_builds_correct_command() -> None:
    runner = DummyRunner()
    show_diff_from_history(runner, 3)
    assert runner.commands == [("diff", "HEAD~3")]


def test_show_diff_from_history_rejects_invalid_count() -> None:
    runner = DummyRunner()
    with pytest.raises(GitPulseError):
        show_diff_from_history(runner, 0)


def test_run_combo_commands_runs_steps_in_order() -> None:
    runner = DummyRunner()
    run_combo_commands(runner, [["status"], ["pull", "--rebase"]])
    assert runner.commands == [("status",), ("pull", "--rebase")]
