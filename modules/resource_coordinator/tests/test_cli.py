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
