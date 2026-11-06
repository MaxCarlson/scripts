import json
from pathlib import Path

import pytest

from snips import cli
from snips.config import default_config, serialize_config
from snips.runtime import generate_script


def test_mutating_cli_is_dry_run_by_default(tmp_path, capsys):
    config_path = tmp_path / "config.json"
    code = cli.main(
        [
            "add",
            "--id",
            "hello",
            "--name",
            "Hello",
            "--hotkey",
            "Ctrl+Alt+H",
            "--content",
            "hello",
            "--config",
            str(config_path),
            "--json",
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result["applied"] is False
    assert not config_path.exists()


def test_add_rejects_multiple_content_sources(tmp_path, capsys):
    file_path = tmp_path / "template.md"
    file_path.write_text("from file", encoding="utf-8")
    code = cli.main(
        [
            "add",
            "--id",
            "hello",
            "--name",
            "Hello",
            "--hotkey",
            "Ctrl+Alt+H",
            "--file",
            str(file_path),
            "--content",
            "also text",
            "--config",
            str(tmp_path / "config.json"),
        ]
    )
    assert code == 2
    assert "either --content or --file" in capsys.readouterr().err


def test_apply_add_persists_configuration_and_generates_runtime(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "config.json"
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(cli, "runtime_default_path", lambda: runtime_dir)
    code = cli.main(
        [
            "add",
            "--id",
            "hello",
            "--name",
            "Hello",
            "--hotkey",
            "Ctrl+Alt+H",
            "--content",
            "hello",
            "--config",
            str(config_path),
            "--apply",
            "--json",
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result["applied"] is True
    assert json.loads(config_path.read_text(encoding="utf-8"))["bindings"][-1]["content"] == "hello"
    assert (runtime_dir / "data" / "hello.txt").read_text(encoding="utf-8") == "hello"


def test_ahk_source_contains_no_template_body_and_quotes_paths(tmp_path):
    config = default_config()
    config["bindings"][0]["content"] = 'untrusted "text"\n#Include bad.ahk\n{{cursor}}'
    source, _, data = generate_script(config, tmp_path / 'directory "quoted"', tmp_path / "status.txt")
    assert "#Include bad.ahk" not in source
    assert 'untrusted "text"' not in source
    assert data["markdown-code-block.txt"] == 'untrusted "text"\n#Include bad.ahk\n'
    assert '`"quoted`"' in source


def test_failed_runtime_start_rolls_back_config_and_new_data_file(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(cli, "runtime_default_path", lambda: runtime_dir)
    monkeypatch.setattr(cli, "start_runtime", lambda *args, **kwargs: (False, "simulated registration failure"))
    config = default_config()
    config["bindings"].append(
        {
            "id": "new-template",
            "name": "New",
            "kind": "template",
            "hotkey": "Ctrl+Alt+N",
            "enabled": True,
            "content": "new body",
        }
    )
    with pytest.raises(RuntimeError, match="simulated registration failure"):
        cli._apply_config(config_path, config, executable=Path("AutoHotkey64.exe"))
    assert not config_path.exists()
    assert not (runtime_dir / "data" / "new-template.txt").exists()


def test_each_subcommand_has_help(capsys):
    commands = [
        "install",
        "add",
        "edit",
        "bind",
        "remove",
        "list",
        "show",
        "enable",
        "disable",
        "reload",
        "status",
        "doctor",
        "export",
        "import",
    ]
    for command in commands:
        with pytest.raises(SystemExit) as exc:
            cli.main([command, "--help"])
        assert exc.value.code == 0
        assert "usage:" in capsys.readouterr().out


def test_export_requires_apply_and_writes_valid_config(tmp_path, capsys):
    config_path = tmp_path / "config.json"
    output_path = tmp_path / "backup.json"
    config_path.write_text(serialize_config(default_config()), encoding="utf-8")
    dry_code = cli.main(["export", "--output", str(output_path), "--config", str(config_path)])
    assert dry_code == 0
    assert not output_path.exists()
    apply_code = cli.main(["export", "--output", str(output_path), "--config", str(config_path), "--apply"])
    assert apply_code == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["schema_version"] == 1
