"""CLI acceptance tests including Scenario F (dry-run default), JSON output, and flag conventions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from agent_continuity.cli import build_parser, main


def _collect_actions(parser: argparse.ArgumentParser) -> list[argparse.Action]:
    actions = list(parser._actions)
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                actions.extend(_collect_actions(sub))
    return actions


def test_every_cli_option_has_short_and_long_form() -> None:
    parser = build_parser()
    for action in _collect_actions(parser):
        if not action.option_strings or action.dest == "help":
            continue
        shorts = [opt for opt in action.option_strings if opt.startswith("-") and not opt.startswith("--")]
        longs = [opt for opt in action.option_strings if opt.startswith("--")]
        assert shorts, f"Option {action.option_strings} is missing a short flag"
        assert longs, f"Option {action.option_strings} is missing a long flag"


def test_scenario_f_mutating_commands_default_to_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    home = tmp_path / "cli_home"

    # 1. wf add without --apply leaves home untouched
    rc = main(["-H", str(home), "wf", "add", "-w", "procwatch", "-t", "ProcWatch", "-j"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["applied"] is False
    assert not home.exists()

    # Apply wf add
    rc = main(["-H", str(home), "wf", "add", "-w", "procwatch", "-t", "ProcWatch", "-u", "https://chatgpt.com/c/abc", "-a", "-j"])
    assert rc == 0
    wf_payload = json.loads(capsys.readouterr().out)
    assert wf_payload["applied"] is True
    wf_id = wf_payload["details"]["workflow_id"]

    # 2. wf gui-add dry-run vs apply
    events_before = list((home / "events").rglob("*.json"))
    rc = main(["-H", str(home), "wf", "gui-add", "-w", wf_id, "-u", "https://chatgpt.com/c/def", "-j"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["applied"] is False
    assert list((home / "events").rglob("*.json")) == events_before

    # 3. link dry-run vs apply
    rc = main(["-H", str(home), "link", "-w", "procwatch", "-p", "codex", "-s", "ses-1", "-e", "windows", "-j"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["applied"] is False
    assert list((home / "events").rglob("*.json")) == events_before

    rc = main(["-H", str(home), "link", "-w", "procwatch", "-p", "codex", "-s", "ses-1", "-e", "windows", "-a", "-j"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["applied"] is True

    # 4. status dry-run vs apply
    events_before = list((home / "events").rglob("*.json"))
    rc = main(["-H", str(home), "status", "-p", "codex", "-s", "ses-1", "-e", "windows", "-S", "paused", "-j"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["applied"] is False
    assert list((home / "events").rglob("*.json")) == events_before

    # 5. unlink dry-run vs apply
    rc = main(["-H", str(home), "unlink", "-w", "procwatch", "-p", "codex", "-s", "ses-1", "-e", "windows", "-j"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["applied"] is False
    assert list((home / "events").rglob("*.json")) == events_before

    # 6. wf archive dry-run
    rc = main(["-H", str(home), "wf", "archive", "-w", "procwatch", "-j"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["applied"] is False
    assert list((home / "events").rglob("*.json")) == events_before

    # 7. rebuild dry-run
    rc = main(["-H", str(home), "rebuild", "-j"])
    assert rc == 0
    rb_dry = json.loads(capsys.readouterr().out)
    assert rb_dry["applied"] is False


def test_cli_end_to_end_find_inbox_doctor_and_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    home = tmp_path / "cli_e2e"
    assert main(["-H", str(home), "wf", "add", "-w", "demo", "-t", "Demo", "-a"]) == 0
    capsys.readouterr()

    assert main(["-H", str(home), "link", "-w", "demo", "-p", "agy", "-s", "conv-1", "-e", "wsl:Ubuntu", "-a"]) == 0
    capsys.readouterr()

    assert main(["-H", str(home), "find", "-w", "demo", "-j"]) == 0
    find_data = json.loads(capsys.readouterr().out)
    assert find_data["ok"] is True
    assert len(find_data["sessions"]) == 1
    assert find_data["sessions"][0]["resume"]["display_command"] == "agy --conversation conv-1"

    assert main(["-H", str(home), "wf", "list", "-j"]) == 0
    wf_list = json.loads(capsys.readouterr().out)
    assert len(wf_list["workflows"]) == 1

    assert main(["-H", str(home), "inbox", "-j"]) == 0
    inbox_data = json.loads(capsys.readouterr().out)
    assert inbox_data["ok"] is True

    assert main(["-H", str(home), "doctor", "-v", "-j"]) == 0
    doc_data = json.loads(capsys.readouterr().out)
    assert doc_data["ok"] is True
    assert doc_data["database"]["schema_version"] == 4

    # Missing workflow returns nonzero with structured JSON error
    rc = main(["-H", str(home), "find", "-w", "nonexistent", "-j"])
    assert rc != 0
    err_data = json.loads(capsys.readouterr().out)
    assert err_data["ok"] is False
    assert err_data["error"]["code"] == "workflow_not_found"
