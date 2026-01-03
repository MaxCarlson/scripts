"""Tests for GitPulse helper utilities."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Sequence

import pytest

from gitpulse.cli import (
    GitPulseError,
    build_default_commit_message,
    run_combo_commands,
    run_sync_flow,
    show_diff_from_history,
)


class DummyRunner:
    """Test double that records git commands invoked."""

    def __init__(self, responses: dict[Sequence[str], str | list[str]] | None = None) -> None:
        self.commands: list[Sequence[str]] = []
        self.responses = {tuple(key): value for key, value in (responses or {}).items()}
        self._last_stdout: dict[Sequence[str], str] = {}

    def run(self, git_args: Sequence[str], *, capture_output: bool = False):
        self.commands.append(tuple(git_args))
        stdout = ""
        if capture_output:
            key = tuple(git_args)
            value = self.responses.get(key, "")
            if isinstance(value, list):
                if value:
                    stdout = value.pop(0)
                    self._last_stdout[key] = stdout
                    if not value:
                        self.responses[key] = stdout
                else:
                    stdout = self._last_stdout.get(key, "")
            else:
                stdout = value
        return SimpleNamespace(stdout=stdout)


def test_build_default_commit_message_counts_files() -> None:
    status_output = "M  README.md\nA  new_file.py\nD  old_file.txt\n"
    message = build_default_commit_message(status_output)
    assert message == "Modified: README.md; Added: new_file.py; Deleted: old_file.txt"


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


def test_run_sync_flow_commits_when_only_staged() -> None:
    responses = {("status", "--porcelain"): ["M  README.md\n", ""]}
    runner = DummyRunner(responses=responses)
    run_sync_flow(runner, assume_yes=True)
    assert runner.commands == [
        ("status",),
        ("pull",),
        ("status", "--porcelain"),
        ("commit", "-m", "Modified: README.md"),
        ("status", "--porcelain"),
        ("push",),
    ]


def test_run_sync_flow_split_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = {
        ("status", "--porcelain"): [
            "M  README.md\n M config.yaml\n",
            " M config.yaml\n",
            "M  config.yaml\n",
            "",
        ]
    }
    runner = DummyRunner(responses=responses)

    monkeypatch.setattr("gitpulse.cli.ask_commit_action", lambda has_unstaged, assume_yes: "split")
    run_sync_flow(runner, assume_yes=True)
    assert runner.commands == [
        ("status",),
        ("pull",),
        ("status", "--porcelain"),
        ("commit", "-m", "Modified: README.md"),
        ("status", "--porcelain"),
        ("add", "--all"),
        ("status",),
        ("status", "--porcelain"),
        ("commit", "-m", "Modified: config.yaml"),
        ("status", "--porcelain"),
        ("push",),
    ]


def test_run_sync_flow_stages_and_commits_unstaged() -> None:
    responses = {
        ("status", "--porcelain"): [
            " M config.yaml\n?? new.txt\n",
            "M  config.yaml\nA  new.txt\n",
            "",
        ]
    }
    runner = DummyRunner(responses=responses)
    run_sync_flow(runner, assume_yes=True)
    assert runner.commands == [
        ("status",),
        ("pull",),
        ("status", "--porcelain"),
        ("add", "--all"),
        ("status",),
        ("status", "--porcelain"),
        ("commit", "-m", "Modified: config.yaml; Added: new.txt"),
        ("status", "--porcelain"),
        ("push",),
    ]


def test_run_sync_flow_can_skip_staging(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = {("status", "--porcelain"): " M config.yaml\n"}
    runner = DummyRunner(responses=responses)
    monkeypatch.setattr("gitpulse.cli.prompt_stage_action", lambda context, assume_yes: ("skip", None))
    run_sync_flow(runner, assume_yes=False)
    assert runner.commands == [
        ("status",),
        ("pull",),
        ("status", "--porcelain"),
        ("push",),
    ]


def test_run_sync_flow_custom_patterns(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = {
        ("status", "--porcelain"): [
            " M config.yaml\n?? docs/new.txt\n",
            "M  config.yaml\n?? docs/new.txt\n",
            "?? docs/new.txt\n",
        ]
    }
    runner = DummyRunner(responses=responses)
    monkeypatch.setattr("gitpulse.cli.prompt_stage_action", lambda context, assume_yes: ("patterns", ["config.yaml"]))
    monkeypatch.setattr("gitpulse.cli.ask_yes_no", lambda prompt, assume_yes: True)
    monkeypatch.setattr("gitpulse.cli.collect_commit_message", lambda entries, assume_yes: "Modified: config.yaml")
    run_sync_flow(runner, assume_yes=False)
    assert runner.commands == [
        ("status",),
        ("pull",),
        ("status", "--porcelain"),
        ("add", "--", "config.yaml"),
        ("status",),
        ("status", "--porcelain"),
        ("commit", "-m", "Modified: config.yaml"),
        ("status", "--porcelain"),
        ("push",),
    ]
