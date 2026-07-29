from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from rrbackup import application, cli_runtime
from rrbackup.command_contract import MAJOR_COMMANDS
from rrbackup.models import ExecutionMode, RunRecord, RunState
from rrbackup.restic import ResticCommand

UTC = timezone.utc


def _subparser_choices(parser: argparse.ArgumentParser) -> set[str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("No root subparser action found.")


def test_root_parser_has_exactly_seven_task_areas() -> None:
    parser = application.build_parser("backup")

    assert _subparser_choices(parser) == set(MAJOR_COMMANDS)
    assert tuple(MAJOR_COMMANDS) == (
        "create",
        "run",
        "view",
        "schedule",
        "restore",
        "repo",
        "config",
    )
    help_text = parser.format_help()
    for area in MAJOR_COMMANDS:
        assert area in help_text
    assert "rrb" not in help_text
    assert "rrbackup" not in help_text


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_root_help_succeeds(flag: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        application.main([flag])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out.lower()
    assert "usage: backup" in output
    assert "backup create" in output
    assert "backup view" in output


@pytest.mark.parametrize("area", MAJOR_COMMANDS)
def test_major_area_help_succeeds(
    area: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        application.main([area, "--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out.lower()
    assert "usage:" in output
    assert area in output


def test_view_help_is_condensed() -> None:
    parser = application.build_parser("backup")
    view_args = parser.parse_args(["view", "--section", "history", "--plain"])

    assert view_args.section == "history"
    assert view_args.plain
    root_action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    help_text = root_action.choices["view"].format_help()
    assert "--section" in help_text
    for old_command in (
        "timeline",
        "snapshots",
        "runs",
        "logs",
        "storage",
        "gaps",
        "health",
        "system",
        "provenance",
    ):
        assert "  {0}".format(old_command) not in help_text


def test_repo_is_public_spelling_and_repository_is_hidden_alias() -> None:
    parser = application.build_parser("backup")
    args = parser.parse_args(["repo", "--refresh-storage", "--plain"])

    assert args.area == "repo"
    assert args.refresh_storage
    assert application._translate_hidden_aliases(["repository", "check"]) == [
        "repo",
        "check",
    ]


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["view", "dashboard"], ["view", "--section", "overview"]),
        (["view", "timeline", "--plain"], ["view", "--section", "history", "--plain"]),
        (["view", "system"], ["view", "--section", "diagnostics"]),
        (["view", "audit", "--json"], ["view", "--section", "audit", "--json"]),
        (["schedule", "list"], ["schedule"]),
        (["edit", "show"], ["config", "show"]),
        (
            ["--config", "settings.toml", "view", "dashboard"],
            ["--config", "settings.toml", "view", "--section", "overview"],
        ),
    ],
)
def test_hidden_aliases_translate_without_appearing_in_help(
    arguments: list[str],
    expected: list[str],
) -> None:
    assert application._translate_hidden_aliases(arguments) == expected


class FakeDefinition:
    def __init__(self) -> None:
        self.name = "local-main"
        self.profile = SimpleNamespace(
            extra_backup_args=[],
            status_file="status.json",
            name="local-main",
            tag="local-main",
        )
        self.materialize_count = 0

    def materialize_inputs(self) -> None:
        self.materialize_count += 1


class FakeInventoryRecord:
    def __init__(self) -> None:
        self.definition = FakeDefinition()
        self.health = SimpleNamespace(healthy=False, severity=SimpleNamespace(value="critical"))
        self.latest_snapshot = None
        self.latest_run = None
        self.scheduler_record = None
        self.next_run = None
        self.missed_runs = None
        self.warnings: tuple[str, ...] = tuple()

    def to_dict(self) -> dict[str, Any]:
        return {"name": "local-main", "health": {"severity": "critical"}}


class FakeInventory:
    def __init__(self) -> None:
        self.records = (FakeInventoryRecord(),)
        self.warnings: tuple[str, ...] = tuple()

    def by_name(self, name: str) -> FakeInventoryRecord:
        assert name == "local-main"
        return self.records[0]

    def to_dict(self) -> dict[str, Any]:
        return {"backups": [record.to_dict() for record in self.records], "warnings": []}


def test_run_auto_json_lists_configured_backups_without_execution(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli_runtime, "inventory", lambda args: FakeInventory())

    result = application.main(["run", "auto", "--json"])

    assert result == application.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["backups"][0]["name"] == "local-main"


def test_print_command_only_never_materializes_inputs_or_executes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_inventory = FakeInventory()
    command = ResticCommand(
        argv=("restic", "-r", "repo", "backup", "--files-from-verbatim", "sources.txt")
    )

    class FakeEngine:
        def __init__(self, profile: object) -> None:
            self.profile = profile

        def build_backup_command(self) -> ResticCommand:
            return command

        def run(self, **kwargs: object) -> object:
            raise AssertionError("execution must not occur for print-only")

    monkeypatch.setattr(cli_runtime, "inventory", lambda args: fake_inventory)
    monkeypatch.setattr(cli_runtime, "BackupEngine", FakeEngine)

    result = application.main(
        ["run", "local-main", "--print-command-only", "--json"]
    )

    assert result == application.EXIT_OK
    assert fake_inventory.records[0].definition.materialize_count == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["executed"] is False
    assert payload["results"][0]["mode"] == "preview"


def test_real_run_materializes_inputs_and_preserves_skipped_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_inventory = FakeInventory()
    run_record = RunRecord.create(profile="local-main", backup_set="local-main")
    run_record = run_record.transition(RunState.SKIPPED, reason="CPU threshold exceeded.")

    class FakeEngine:
        def __init__(self, profile: object) -> None:
            self.profile = profile

        def run(self, **kwargs: object) -> object:
            assert kwargs["mode"] == ExecutionMode.RUN
            return SimpleNamespace(record=run_record, summary=None, execution=None)

    monkeypatch.setattr(cli_runtime, "inventory", lambda args: fake_inventory)
    monkeypatch.setattr(cli_runtime, "BackupEngine", FakeEngine)

    result = application.main(["run", "local-main", "--json"])

    assert result == application.EXIT_SKIPPED
    assert fake_inventory.records[0].definition.materialize_count == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["record"]["state"] == "skipped"
