"""Tests for GitPulse helper utilities."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Sequence

import pytest

from gitpulse.cli import (
    GitPulseError,
    ask_commit_action,
    build_default_commit_message,
    run_combo_commands,
    run_sync_flow,
    show_diff_from_history,
)

RED = "\x1b[31m"
GREEN = "\x1b[32m"
RESET = "\x1b[0m"


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
    stats = {
        "README.md": (12, 3),
        "new_file.py": (45, 0),
        "old_file.txt": (0, 10),
    }
    message = build_default_commit_message(status_output, stats)
    expected = (
        "Modified\n"
        f"  {RED}-3{RESET} {GREEN}+12{RESET}\tREADME.md\n\n"
        "Added\n"
        f"  {RED}-0{RESET} {GREEN}+45{RESET}\tnew_file.py\n\n"
        "Deleted\n"
        f"  {RED}-10{RESET} {GREEN}+0{RESET}\told_file.txt"
    )
    assert message == expected


def test_ask_commit_action_accepts_quoted_message(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(['"My feature commit"'])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    choice = ask_commit_action(has_unstaged=False, assume_yes=False)
    assert choice == "My feature commit"


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
    responses = {
        ("status", "--porcelain"): ["M  README.md\n", ""],
        ("diff", "--cached", "--numstat"): ["5\t1\tREADME.md\n"],
    }
    runner = DummyRunner(responses=responses)
    run_sync_flow(runner, assume_yes=True)
    commit_msg = "Modified\n  {red}-1{reset} {green}+5{reset}\tREADME.md".format(
        red=RED, green=GREEN, reset=RESET
    )
    assert runner.commands == [
        ("status",),
        ("pull",),
        ("status", "--porcelain"),
        ("diff", "--cached", "--numstat"),
        ("commit", "-m", commit_msg),
        ("status", "--porcelain"),
        ("push",),
    ]


def test_run_sync_flow_uses_custom_commit_message(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = {
        ("status", "--porcelain"): ["M  README.md\n", ""],
        ("diff", "--cached", "--numstat"): ["5\t1\tREADME.md\n"],
    }
    runner = DummyRunner(responses=responses)

    def fake_input(prompt: str) -> str:
        if "Commit staged changes" in prompt:
            return '"Custom sync message"'
        raise AssertionError("Unexpected prompt")

    monkeypatch.setattr("builtins.input", fake_input)

    def fail_collect(*args, **kwargs):
        raise AssertionError("collect_commit_message should not be called when custom message provided.")

    monkeypatch.setattr("gitpulse.cli.collect_commit_message", fail_collect)

    run_sync_flow(runner, assume_yes=False)
    assert ("commit", "-m", "Custom sync message") in runner.commands


def test_run_sync_flow_split_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = {
        ("status", "--porcelain"): [
            "M  README.md\n M config.yaml\n",
            " M config.yaml\n",
            "M  config.yaml\n",
            "",
        ],
        ("diff", "--cached", "--numstat"): [
            "5\t1\tREADME.md\n",
            "2\t0\tconfig.yaml\n",
        ]
    }
    runner = DummyRunner(responses=responses)

    monkeypatch.setattr("gitpulse.cli.ask_commit_action", lambda has_unstaged, assume_yes: "split")
    run_sync_flow(runner, assume_yes=True)
    msg_first = "Modified\n  {red}-1{reset} {green}+5{reset}\tREADME.md".format(red=RED, green=GREEN, reset=RESET)
    msg_second = "Modified\n  {red}-0{reset} {green}+2{reset}\tconfig.yaml".format(
        red=RED, green=GREEN, reset=RESET
    )
    assert runner.commands == [
        ("status",),
        ("pull",),
        ("status", "--porcelain"),
        ("diff", "--cached", "--numstat"),
        ("commit", "-m", msg_first),
        ("status", "--porcelain"),
        ("add", "--all"),
        ("status",),
        ("status", "--porcelain"),
        ("diff", "--cached", "--numstat"),
        ("commit", "-m", msg_second),
        ("status", "--porcelain"),
        ("push",),
    ]


def test_run_sync_flow_stages_and_commits_unstaged() -> None:
    responses = {
        ("status", "--porcelain"): [
            " M config.yaml\n?? new.txt\n",
            "M  config.yaml\nA  new.txt\n",
            "",
        ],
        ("diff", "--cached", "--numstat"): [
            "4\t1\tconfig.yaml\n50\t0\tnew.txt\n",
        ]
    }
    runner = DummyRunner(responses=responses)
    run_sync_flow(runner, assume_yes=True)
    msg = (
        "Modified\n"
        f"  {RED}-1{RESET} {GREEN}+4{RESET}\tconfig.yaml\n\n"
        "Added\n"
        f"  {RED}-0{RESET} {GREEN}+50{RESET}\tnew.txt"
    )
    assert runner.commands == [
        ("status",),
        ("pull",),
        ("status", "--porcelain"),
        ("add", "--all"),
        ("status",),
        ("status", "--porcelain"),
        ("diff", "--cached", "--numstat"),
        ("commit", "-m", msg),
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
        ],
        ("diff", "--cached", "--numstat"): ["3\t1\tconfig.yaml\n"],
    }
    runner = DummyRunner(responses=responses)
    monkeypatch.setattr("gitpulse.cli.prompt_stage_action", lambda context, assume_yes: ("patterns", ["config.yaml"]))
    monkeypatch.setattr("gitpulse.cli.ask_yes_no", lambda prompt, assume_yes: True)
    monkeypatch.setattr(
        "gitpulse.cli.collect_commit_message",
        lambda entries, assume_yes, stats: "Modified\n  custom",
    )
    run_sync_flow(runner, assume_yes=False)
    assert runner.commands == [
        ("status",),
        ("pull",),
        ("status", "--porcelain"),
        ("add", "--", "config.yaml"),
        ("status",),
        ("status", "--porcelain"),
        ("diff", "--cached", "--numstat"),
        ("commit", "-m", "Modified\n  custom"),
        ("status", "--porcelain"),
        ("push",),
    ]
