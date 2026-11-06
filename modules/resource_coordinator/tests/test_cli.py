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
    args = parse_args(["miner", "pause", "-d", "2h"])
    assert args.command == "miner"
    assert args.miner_command == "pause"
    assert args.duration == "2h"


def test_cli_parse_args_self_managed_operations():
    from resource_coordinator.cli import parse_args

    setup = parse_args(["setup"])
    assert setup.command == "setup"
    assert setup.apply is False
    assert setup.json is False

    applied_setup = parse_args(["setup", "--apply", "--json", "--non-interactive"])
    assert applied_setup.apply is True
    assert applied_setup.json is True
    assert applied_setup.non_interactive is True

    doctor = parse_args(["doctor", "-j"])
    assert doctor.command == "doctor"
    assert doctor.json is True

    repair = parse_args(["repair", "--apply", "--non-interactive"])
    assert repair.command == "repair"
    assert repair.apply is True
    assert repair.non_interactive is True

    teardown = parse_args(["teardown", "-a"])
    assert teardown.command == "teardown"
    assert teardown.apply is True

    startup_status = parse_args(["startup", "status", "-j"])
    assert startup_status.startup_command == "status"
    assert startup_status.json is True

    boot_install = parse_args(["startup", "install", "-m", "boot", "-a"])
    assert boot_install.startup_command == "install"
    assert boot_install.mode == "boot"
    assert boot_install.apply is True

    logon_install = parse_args(["startup", "install", "-m", "logon", "-a"])
    assert logon_install.mode == "logon"

    for action in ("enable", "disable", "repair", "uninstall"):
        parsed = parse_args(["startup", action, "-a"])
        assert parsed.startup_command == action
        assert parsed.apply is True


def test_cli_miner_control_commands_and_duration_parser():
    from resource_coordinator.cli import _parse_hold_duration

    assert _parse_hold_duration("2h") == 7200
    assert _parse_hold_duration("30m") == 1800
    for action in ("start", "stop", "resume"):
        args = parse_args(["miner", action])
        assert args.miner_command == action
    assert parse_args(["gaming", "start"]).gaming_command == "start"
    assert parse_args(["gaming", "stop"]).gaming_command == "stop"
    assert parse_args(["gaming", "status"]).gaming_command == "status"
    logs = parse_args(["logs", "krig", "--follow", "--tail-bytes", "1024"])
    assert logs.process_name == "krig" and logs.follow and logs.tail_bytes == 1024
    conditional = parse_args(["miner", "pause", "--until-gpu-below", "20", "--window", "60s"])
    assert conditional.until_gpu_below == 20 and conditional.window == "60s"


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


def test_cli_parse_args_serve_options():
    args = parse_args(["serve", "--start-miner", "--stop-miner-on-shutdown", "--drain-timeout", "15.0"])
    assert args.command == "serve"
    assert args.start_miner is True
    assert args.stop_miner_on_shutdown is True
    assert args.drain_timeout == 15.0


def test_cli_parse_args_generic_process_controls():
    args = parse_args(["serve", "--fake-process", "--start-process", "worker", "--stop-process-on-shutdown", "worker"])
    assert args.fake_miner is True
    assert args.start_process == "worker"
    assert args.stop_process_on_shutdown == "worker"


def test_cli_parse_args_preflight():
    args = parse_args(["preflight", "-c", "config.yaml", "-f", "-j"])
    assert args.command == "preflight"
    assert args.config == "config.yaml"
    assert args.fake_miner is True
    assert args.json is True


def test_cli_parse_args_abort():
    args = parse_args(["abort", "-u", "http://localhost:1235", "-r", "test emergency abort", "-j"])
    assert args.command == "abort"
    assert args.url == "http://localhost:1235"
    assert args.reason == "test emergency abort"
    assert args.json is True


def test_cli_parse_args_coordinator_lifecycle():
    for action in ("restart", "shutdown"):
        args = parse_args([action, "-u", "http://localhost:1235", "-r", "activate config", "-j"])
        assert args.command == action
        assert args.reason == "activate config"
        assert args.json is True


def test_cli_coordinator_lifecycle_discovers_credential_automatically(monkeypatch):
    from unittest.mock import MagicMock
    import httpx
    from resource_coordinator.cli import cmd_lifecycle

    monkeypatch.delenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", raising=False)
    monkeypatch.delenv("RESOURCE_COORDINATOR_RECOVERY_TOKEN", raising=False)
    monkeypatch.setattr("resource_coordinator.cli.load_or_create_token", lambda: "A" * 64)
    response = MagicMock(status_code=202)
    response.json.return_value = {"status": "draining"}
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = response
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: client)
    args = parse_args(["shutdown"])
    assert cmd_lifecycle(args) == 0
    assert client.post.call_args.kwargs["headers"]["Authorization"] == "Bearer " + "A" * 64


def test_auth_doctor_is_offline_and_never_prints_token(tmp_path, monkeypatch, capsys):
    from resource_coordinator.cli import cmd_auth
    from resource_coordinator.core import operator_credentials

    token_path = tmp_path / "operator-token"
    token_path.write_text("A" * 64, encoding="ascii")
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(token_path))
    monkeypatch.delenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", raising=False)
    monkeypatch.setattr(operator_credentials, "_acl_is_restricted", lambda _path: True)
    args = parse_args(["auth", "doctor"])

    assert cmd_auth(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["credential_path"] == str(token_path)
    assert "A" * 64 not in output


def test_cli_cmd_preflight(tmp_path, capsys):
    from resource_coordinator.cli import cmd_preflight

    cfg = tmp_path / "valid.yaml"
    cfg.write_text("version: '1.0'\nprocesses: {}\npolicies: []\n", encoding="utf-8")
    args = parse_args(["preflight", "-c", str(cfg), "-f", "-j"])
    code = cmd_preflight(args)
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["passed"] is True


def test_cli_cmd_abort_mock(monkeypatch, capsys):
    from unittest.mock import MagicMock
    import httpx
    from resource_coordinator.cli import cmd_abort

    monkeypatch.setenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", "test-token")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "aborted",
        "state": "stopped",
        "message": "Emergency abort executed",
    }

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.post.return_value = mock_resp

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: mock_client)

    args = parse_args(["abort", "-r", "manual abort test", "-j"])
    code = cmd_abort(args)
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "aborted"


def test_cli_status_displays_managed_process_state(monkeypatch, capsys):
    from unittest.mock import MagicMock
    import httpx
    from resource_coordinator.cli import cmd_status

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "online",
        "service_state": "ready",
        "is_ready": True,
        "upstream_url": "http://127.0.0.1:1234",
        "gpu_inference": {
            "active_count": 0,
            "pending_count": 0,
            "is_cooling_down": True,
            "cooldown_remaining": 17.2,
            "is_restart_inhibited": False,
        },
        "processes": {
            "background_worker": {
                "state": "stopped",
                "pid": None,
                "lifecycle_owner": "unmanaged",
                "is_coordinator_owned": False,
                "was_stopped_by_coordinator": True,
            }
        },
    }
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.return_value = mock_response
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: mock_client)

    args = parse_args(["status", "--url", "http://127.0.0.1:1235"])
    assert cmd_status(args) == 0
    output = capsys.readouterr().out
    assert "Process background_worker: stopped" in output
    assert "stopped by coordinator: True" in output
    assert "Cooldown remaining: 17.2s" in output
