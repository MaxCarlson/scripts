import json

from resource_coordinator.cli import cmd_config, parse_args


def test_cli_parse_args_serve():
    args = parse_args(["serve", "-l", "127.0.0.1:1235", "-u", "http://127.0.0.1:1234", "-f"])
    assert args.command == "serve"
    assert args.listen == "127.0.0.1:1235"
    assert args.upstream == "http://127.0.0.1:1234"
    assert args.fake_miner is True


def test_cli_parse_args_status():
    args = parse_args(["status", "-u", "http://localhost:1235", "-j"])
    assert args.command == "status"
    assert args.url == "http://localhost:1235"
    assert args.json is True


def test_cli_parse_args_miner():
    args = parse_args(["miner", "pause", "-t", "5.0"])
    assert args.command == "miner"
    assert args.miner_command == "pause"
    assert args.timeout == 5.0


def test_cli_config_show(capsys):
    args = parse_args(["config", "show", "-j"])
    code = cmd_config(args)
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["version"] == "1.0"
    assert "krig" in data["processes"]


def test_cli_config_show_text(capsys):
    args = parse_args(["config", "show"])
    code = cmd_config(args)
    assert code == 0
    captured = capsys.readouterr()
    assert "Version:   1.0" in captured.out
    assert "127.0.0.1:1235" in captured.out


def test_cli_config_validate(tmp_path, capsys):
    valid_cfg = tmp_path / "valid.yaml"
    valid_cfg.write_text("version: '1.0'\nprocesses: {}\npolicies: []\n", encoding="utf-8")
    args = parse_args(["config", "validate", "-c", str(valid_cfg)])
    code = cmd_config(args)
    assert code == 0
    captured = capsys.readouterr()
    assert "Configuration is valid." in captured.out
