from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from rrbackup import application
from rrbackup.command_contract import MAJOR_COMMANDS
from rrbackup.models import ExecutionMode, RunRecord, RunState
from rrbackup.restic import ExecutionResult, ResticCommand


UTC = timezone.utc


def _subparser_choices(parser: argparse.ArgumentParser) -> set[str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("No root subparser action found.")


def test_root_parser_has_exactly_six_major_areas() -> None:
    parser = application.build_parser("backup")

    assert _subparser_choices(parser) == set(MAJOR_COMMANDS)
    help_text = parser.format_help()
    for area in MAJOR_COMMANDS:
        assert area in help_text
    assert "edit -> config" in help_text


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_root_help_succeeds(flag: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        application.main([flag], program_name="backup")

    assert exc_info.value.code == 0
    assert "usage:" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("area", MAJOR_COMMANDS)
def test_major_area_help_succeeds(
    area: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        application.main([area, "--help"], program_name="backup")

    assert exc_info.value.code == 0
    output = capsys.readouterr().out.lower()
    assert "usage:" in output
    assert area in output


def test_view_default_and_repository_stats_options_parse_without_conflict() -> None:
    parser = application.build_parser("backup")

    view_args = parser.parse_args(["view", "--json"])
    stats_args = parser.parse_args(
        ["repository", "stats", "--mode", "restore-size", "--markdown"]
    )

    assert view_args.view_command == "dashboard"
    assert view_args.json
    assert stats_args.mode == "restore-size"
    assert stats_args.markdown


def test_edit_alias_and_legacy_commands_translate() -> None:
    assert application._translate_legacy(["edit", "effective"])[0] == [
        "config",
        "effective",
    ]
    assert application._translate_legacy(["list", "--tag", "local-main"])[0] == [
        "view",
        "snapshots",
        "--tag",
        "local-main",
    ]
    assert application._translate_legacy(
        ["--config", "settings.json", "backup", "--set", "daily", "--dry-run"]
    )[0] == [
        "--config",
        "settings.json",
        "run",
        "daily",
        "--dry-run",
    ]


def test_legacy_mutating_commands_remain_delegated() -> None:
    assert application._translate_legacy(["setup"])[1]
    assert application._translate_legacy(["prune"])[1]
    assert application._translate_legacy(["config", "init"])[1]


def test_print_command_only_is_json_clean_and_never_executes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = ResticCommand(argv=("restic", "-r", "repo", "backup"))
    now = datetime(2026, 7, 29, tzinfo=UTC)
    preview = ExecutionResult(
        command=command,
        mode=ExecutionMode.PREVIEW,
        executed=False,
        return_code=None,
        started_utc=now,
        finished_utc=now,
        output=tuple(),
    )

    class FakeEngine:
        def __init__(self, profile: object) -> None:
            self.profile = profile

        def preview(self) -> ExecutionResult:
            return preview

    monkeypatch.setattr(application, "_load_profile", lambda args: SimpleNamespace(extra_backup_args=[]))
    monkeypatch.setattr(application, "BackupEngine", FakeEngine)

    result = application.main(
        ["run", "local-main", "--print-command-only", "--json"],
        program_name="backup",
    )

    assert result == application.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["executed"] is False
    assert payload["mode"] == "preview"


def test_skipped_run_returns_distinct_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    record = RunRecord.create(profile="local-main", backup_set="local-main")
    record = record.transition(RunState.SKIPPED, reason="CPU threshold exceeded.")

    class FakeEngine:
        def __init__(self, profile: object) -> None:
            self.profile = profile

        def run(self, **kwargs: object) -> object:
            return SimpleNamespace(
                record=record,
                summary=None,
                execution=None,
            )

    monkeypatch.setattr(application, "_load_profile", lambda args: SimpleNamespace(extra_backup_args=[]))
    monkeypatch.setattr(application, "BackupEngine", FakeEngine)

    result = application.main(["run", "local-main", "--json"], program_name="backup")

    assert result == application.EXIT_SKIPPED
    assert json.loads(capsys.readouterr().out)["record"]["state"] == "skipped"
