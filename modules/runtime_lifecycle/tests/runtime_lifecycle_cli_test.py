from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime_lifecycle import cli


def _write_spec(tmp_path: Path) -> Path:
    path = tmp_path / "task.json"
    path.write_text(
        json.dumps(
            {
                "owner": "snips",
                "name": "runtime",
                "executable": "C:/Python/pythonw.exe",
                "args": ["-m", "snips.cli", "ensure-runtime", "--apply"],
                "working_dir": "C:/Users/test/snips",
                "principal": {"sid": "S-1-5-21-1-2-3-1001"},
                "triggers": [
                    {"type": "logon", "delay": "PT5S"},
                    {"type": "interval", "interval": "PT1M"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_load_spec_builds_typed_models(tmp_path: Path) -> None:
    spec = cli._load_spec(_write_spec(tmp_path))
    assert spec.owner == "snips"
    assert len(spec.triggers) == 2
    assert spec.executable == Path("C:/Python/pythonw.exe")
    assert spec.principal.sid == "S-1-5-21-1-2-3-1001"


def test_apply_command_defaults_to_preview(tmp_path: Path, monkeypatch, capsys) -> None:
    path = _write_spec(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(cli.windows, "preview", lambda spec, **kwargs: calls.append("preview") or {"action": "create"})
    monkeypatch.setattr(cli.windows, "apply", lambda *args, **kwargs: calls.append("apply"))
    assert cli.main(["apply", "-i", str(path), "-j"]) == 0
    assert calls == ["preview"]
    assert '"action": "create"' in capsys.readouterr().out


def test_apply_command_applies_only_with_flag(tmp_path: Path, monkeypatch, capsys) -> None:
    path = _write_spec(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(cli.windows, "apply", lambda spec, **kwargs: calls.append("apply") or {"action": "created"})
    assert cli.main(["apply", "-i", str(path), "-a", "-f", "-j"]) == 0
    assert calls == ["apply"]
    assert '"action": "created"' in capsys.readouterr().out


def test_mutating_task_control_defaults_to_status_preview(monkeypatch, capsys) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli.windows, "status", lambda *args, **kwargs: {"registration_state": "registered"})
    monkeypatch.setattr(cli.windows, "disable", lambda *args, **kwargs: calls.append("disable"))
    assert cli.main(["disable", "-o", "snips", "-N", "runtime", "-j"]) == 0
    assert calls == []
    assert '"applied": false' in capsys.readouterr().out


def test_help_includes_short_and_long_apply_flags(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        cli._parser().parse_args(["apply", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "-a, --apply" in output
    assert "-j, --json" in output
