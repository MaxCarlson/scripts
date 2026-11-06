"""Compatibility contract for the Resource Coordinator command interface."""

import pytest

from resource_coordinator.cli import parse_args


@pytest.mark.parametrize(
    ("argv", "command", "attributes"),
    [
        (["status", "-u", "http://localhost:1235", "-j"], "status", {"json": True}),
        (["miner", "status", "-u", "http://localhost:1235", "-j"], "miner", {"miner_command": "status"}),
        (["miner", "start", "-r", "maintenance"], "miner", {"miner_command": "start", "reason": "maintenance"}),
        (["miner", "pause", "-d", "2h"], "miner", {"duration": "2h"}),
        (["miner", "pause", "--until-gpu-below", "20", "--window", "60s"], "miner",
         {"until_gpu_below": 20.0, "window": "60s"}),
        (["gaming", "status"], "gaming", {"gaming_command": "status"}),
        (["gaming", "start", "-r", "play"], "gaming", {"gaming_command": "start", "reason": "play"}),
        (["gaming", "stop"], "gaming", {"gaming_command": "stop"}),
        (["restart", "-u", "http://localhost:1235", "-r", "upgrade", "-j"], "restart",
         {"reason": "upgrade", "json": True}),
        (["shutdown"], "shutdown", {"reason": "Operator requested shutdown"}),
        (["abort", "-r", "emergency", "-j"], "abort", {"reason": "emergency", "json": True}),
        (["recover", "-r", "gpu.inference", "-n", "reviewed"], "recover",
         {"resource": "gpu.inference", "reason": "reviewed"}),
        (["serve", "-l", "127.0.0.1:1235", "-u", "http://127.0.0.1:1234", "-f"], "serve",
         {"listen": "127.0.0.1:1235", "upstream": "http://127.0.0.1:1234", "fake_miner": True}),
        (["setup", "-a", "-j", "-n", "-m", "boot"], "setup",
         {"apply": True, "json": True, "non_interactive": True, "startup_mode": "boot"}),
        (["upgrade", "-a", "-j", "-n"], "upgrade",
         {"apply": True, "json": True, "non_interactive": True}),
        (["repair", "-a", "-n"], "repair", {"apply": True, "non_interactive": True}),
        (["teardown", "-a", "-j"], "teardown", {"apply": True, "json": True}),
        (["startup", "install", "-m", "logon", "-a", "-j"], "startup",
         {"startup_command": "install", "mode": "logon", "apply": True}),
        (["startup", "enable", "-a"], "startup", {"startup_command": "enable", "apply": True}),
        (["auth", "doctor"], "auth", {"auth_command": "doctor"}),
        (["auth", "repair"], "auth", {"auth_command": "repair"}),
        (["auth", "reinitialize"], "auth", {"auth_command": "reinitialize"}),
        (["config", "show", "-c", "settings.yaml", "-j"], "config",
         {"config_command": "show", "config": "settings.yaml", "json": True}),
        (["config", "validate", "-c", "settings.yaml"], "config",
         {"config_command": "validate", "config": "settings.yaml"}),
        (["doctor", "-j"], "doctor", {"json": True}),
        (["diagnose", "-c", "settings.yaml", "-u", "http://localhost:1235", "-j"], "diagnose",
         {"config": "settings.yaml", "url": "http://localhost:1235", "json": True}),
        (["preflight", "-f", "-j"], "preflight", {"fake_miner": True, "json": True}),
        (["accept", "-u", "http://upstream:1234", "-j"], "accept",
         {"upstream": "http://upstream:1234", "json": True}),
        (["logs", "krig", "-f"], "logs", {"process_name": "krig", "follow": True}),
    ],
)
def test_existing_cli_paths_and_flags_keep_their_parse_contract(argv, command, attributes):
    parsed = parse_args(argv)

    assert parsed.command == command
    for name, expected in attributes.items():
        assert getattr(parsed, name) == expected


@pytest.mark.parametrize(
    ("argv", "operation_id"),
    [
        (["status"], "status"),
        (["control", "miner", "status"], "control.miner.status"),
        (["control", "miner", "start"], "control.miner.start"),
        (["control", "miner", "stop"], "control.miner.stop"),
        (["control", "miner", "pause", "-d", "2h"], "control.miner.pause"),
        (["control", "miner", "resume"], "control.miner.resume"),
        (["control", "gaming", "status"], "control.gaming.status"),
        (["control", "gaming", "on"], "control.gaming.on"),
        (["control", "gaming", "off"], "control.gaming.off"),
        (["service", "restart"], "service.restart"),
        (["service", "shutdown"], "service.shutdown"),
        (["service", "abort"], "service.abort"),
        (["service", "recover", "--reason", "reviewed"], "service.recover"),
        (["service", "run"], "service.run"),
        (["system", "setup"], "system.setup"),
        (["system", "upgrade"], "system.upgrade"),
        (["system", "repair"], "system.repair"),
        (["system", "teardown"], "system.teardown"),
        (["system", "startup", "status"], "system.startup.status"),
        (["system", "startup", "install", "-m", "boot"], "system.startup.install"),
        (["system", "startup", "enable"], "system.startup.enable"),
        (["system", "startup", "disable"], "system.startup.disable"),
        (["system", "startup", "repair"], "system.startup.repair"),
        (["system", "startup", "uninstall"], "system.startup.uninstall"),
        (["system", "auth", "doctor"], "system.auth.doctor"),
        (["system", "auth", "repair"], "system.auth.repair"),
        (["system", "auth", "reinitialize"], "system.auth.reinitialize"),
        (["config", "show"], "config.show"),
        (["config", "validate", "-c", "settings.yaml"], "config.validate"),
        (["check", "health"], "check.health"),
        (["check", "telemetry"], "check.telemetry"),
        (["check", "preflight"], "check.preflight"),
        (["check", "accept"], "check.accept"),
        (["logs", "miner"], "logs"),
        (["miner", "status"], "control.miner.status"),
        (["gaming", "start"], "control.gaming.on"),
        (["restart"], "service.restart"),
        (["serve"], "service.run"),
        (["upgrade"], "system.upgrade"),
        (["doctor"], "check.health"),
        (["diagnose"], "check.telemetry"),
    ],
)
def test_canonical_and_legacy_commands_normalize_to_stable_operations(argv, operation_id):
    parsed = parse_args(argv)

    assert parsed.operation_id == operation_id


def test_primary_help_exposes_only_the_seven_canonical_groups(capsys):
    with pytest.raises(SystemExit) as raised:
        parse_args(["--help"])

    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "{status,control,service,system,config,check,logs}" in output
    assert "==SUPPRESS==" not in output
    positions = [output.index(f"    {command} ") for command in
                 ("status", "control", "service", "system", "config", "check", "logs")]
    assert positions == sorted(positions)


@pytest.mark.parametrize(
    "argv",
    [
        ["control", "-h"], ["control", "miner", "-h"], ["service", "-h"],
        ["system", "-h"], ["system", "startup", "-h"], ["system", "auth", "-h"],
        ["check", "-h"], ["check", "health", "-h"],
    ],
)
def test_canonical_groups_have_contextual_help(argv, capsys):
    with pytest.raises(SystemExit) as raised:
        parse_args(argv)

    assert raised.value.code == 0
    assert "usage: resource-coordinator" in capsys.readouterr().out


def test_check_help_distinguishes_diagnostic_contracts(capsys):
    with pytest.raises(SystemExit) as raised:
        parse_args(["check", "-h"])

    assert raised.value.code == 0
    output = capsys.readouterr().out
    for term in ("health diagnoses", "telemetry reads", "preflight checks", "accept runs supervised"):
        assert term in output


def test_cli_dependency_and_package_versions_are_synchronized():
    from pathlib import Path

    from resource_coordinator import __version__

    project = Path(__file__).parents[1] / "pyproject.toml"
    metadata = project.read_text(encoding="utf-8")
    assert f'version = "{__version__}"' in metadata
    assert '"rich>=13.7,<15"' in metadata


@pytest.mark.parametrize(
    ("argv", "expected_json", "expected_color"),
    [
        (["-j", "status"], True, "auto"),
        (["status", "-j"], True, "auto"),
        (["--color", "never", "status"], False, "never"),
        (["status", "--color", "always"], False, "always"),
        (["-j", "control", "miner", "status", "--color", "never"], True, "never"),
    ],
)
def test_global_and_end_of_command_output_flags_do_not_mask_each_other(argv, expected_json, expected_color):
    parsed = parse_args(argv)

    assert parsed.json is expected_json
    assert parsed.color == expected_color


@pytest.mark.parametrize(
    "argv",
    [
        ["status", "-j"],
        ["control", "miner", "status", "-j"], ["control", "miner", "start", "-j"],
        ["control", "miner", "stop", "-j"], ["control", "miner", "pause", "-d", "2h", "-j"],
        ["control", "miner", "resume", "-j"], ["control", "gaming", "status", "-j"],
        ["control", "gaming", "on", "-j"], ["control", "gaming", "off", "-j"],
        ["service", "restart", "-j"], ["service", "shutdown", "-j"],
        ["service", "abort", "-j"], ["service", "recover", "--reason", "verified", "-j"],
        ["system", "setup", "-j"], ["system", "upgrade", "-j"], ["system", "repair", "-j"],
        ["system", "teardown", "-j"], ["system", "startup", "status", "-j"],
        ["system", "startup", "install", "-m", "logon", "-j"],
        ["system", "startup", "enable", "-j"], ["system", "startup", "disable", "-j"],
        ["system", "startup", "repair", "-j"], ["system", "startup", "uninstall", "-j"],
        ["system", "auth", "doctor", "-j"], ["system", "auth", "repair", "-j"],
        ["system", "auth", "reinitialize", "-j"], ["config", "show", "-j"],
        ["config", "validate", "-c", "settings.yaml", "-j"], ["check", "health", "-j"],
        ["check", "telemetry", "-j"], ["check", "preflight", "-j"], ["check", "accept", "-j"],
        ["miner", "status", "-j"], ["recover", "-n", "verified", "-j"], ["auth", "doctor", "-j"],
    ],
)
def test_structured_leaf_commands_accept_json_at_end(argv):
    assert parse_args(argv).json is True


@pytest.mark.parametrize(
    ("legacy", "canonical", "expected_command", "expected_action"),
    [
        (["miner", "start", "-r", "test"], ["control", "miner", "start", "-r", "test"], "miner", "start"),
        (["gaming", "start"], ["control", "gaming", "on"], "gaming", "start"),
        (["gaming", "stop"], ["control", "gaming", "off"], "gaming", "stop"),
        (["restart"], ["service", "restart"], "restart", None),
        (["serve", "-f"], ["service", "run", "-f"], "serve", None),
        (["setup", "-a"], ["system", "setup", "-a"], "setup", None),
        (["upgrade", "-a"], ["system", "upgrade", "-a"], "upgrade", None),
        (["startup", "install", "-m", "boot"], ["system", "startup", "install", "-m", "boot"],
         "startup", "install"),
        (["auth", "doctor"], ["system", "auth", "doctor"], "auth", "doctor"),
        (["doctor"], ["check", "health"], "doctor", None),
        (["diagnose"], ["check", "telemetry"], "diagnose", None),
        (["preflight"], ["check", "preflight"], "preflight", None),
        (["accept", "-u", "http://upstream:1234"], ["check", "accept", "-u", "http://upstream:1234"],
         "accept", None),
    ],
)
def test_legacy_and_canonical_paths_normalize_to_shared_handler_arguments(
    legacy, canonical, expected_command, expected_action
):
    from resource_coordinator.cli_dispatch import normalize_dispatch_args

    legacy_args = normalize_dispatch_args(parse_args(legacy))
    canonical_args = normalize_dispatch_args(parse_args(canonical))

    assert legacy_args.command == canonical_args.command == expected_command
    assert legacy_args.operation_id == canonical_args.operation_id
    if expected_action is not None:
        action_name = "gaming_command" if expected_command == "gaming" else "startup_command" if expected_command == "startup" else "auth_command" if expected_command == "auth" else "miner_command"
        assert getattr(legacy_args, action_name) == getattr(canonical_args, action_name) == expected_action
    if expected_command == "accept":
        assert legacy_args.upstream == canonical_args.upstream == "http://upstream:1234"


def test_structured_result_renderer_is_human_readable_by_default():
    from io import StringIO

    from resource_coordinator.presentation import render_result

    output = StringIO()
    render_result("Miner", {"status": "running", "pid": 73392, "owner": "coordinator"}, stream=output,
                  color="never", width=80)

    assert "Miner" in output.getvalue()
    assert "RUNNING" in output.getvalue()
    assert "73392" in output.getvalue()
    assert "{'status':" not in output.getvalue()


def test_json_renderer_emits_one_clean_document():
    from io import StringIO
    import json

    from resource_coordinator.presentation import emit_json

    output = StringIO()
    emit_json({
        "status": "blocked", "message": "safe", "token": "credential",
        "access_token": "access", "apiKey": "key", "token_path": "C:/secrets/operator-token",
    }, stream=output)

    rendered = output.getvalue()
    assert json.loads(rendered) == {
        "status": "blocked", "message": "safe", "token": "[REDACTED]",
        "access_token": "[REDACTED]", "apiKey": "[REDACTED]",
        "token_path": "C:/secrets/operator-token",
    }
    assert "\x1b[" not in rendered
    assert rendered.endswith("\n")


def test_renderer_color_always_and_never_produce_expected_ansi():
    from io import StringIO

    from resource_coordinator.presentation import render_result

    colored = StringIO()
    plain = StringIO()
    render_result("Health", {"status": "ready"}, stream=colored, color="always")
    render_result("Health", {"status": "ready"}, stream=plain, color="never")
    assert "\x1b[" in colored.getvalue()
    assert "\x1b[" not in plain.getvalue()


def test_color_policy_honors_no_color_and_explicit_override():
    from io import StringIO

    from resource_coordinator.presentation import make_console

    stream = StringIO()
    auto = make_console(color="auto", stream=stream, environ={"NO_COLOR": "1"})
    always = make_console(color="always", stream=stream, environ={"NO_COLOR": "1"})
    never = make_console(color="never", stream=stream, environ={})
    assert auto.no_color is True
    assert always.no_color is False
    assert never.no_color is True


def test_semantic_status_colors_keep_intentional_stop_and_unknown_neutral():
    from resource_coordinator.presentation import _status_style

    assert _status_style("ready") == "green"
    assert _status_style("degraded") == "yellow"
    assert _status_style("blocked") == "red"
    assert _status_style("unhealthy") == "red"
    assert _status_style("invalid") == "red"
    assert _status_style("not_ready") == "yellow"
    assert _status_style("stopped") is None
    assert _status_style("disabled") is None
    assert _status_style("unknown") is None


def test_miner_status_renderer_uses_sections_and_human_time_without_flattening():
    from datetime import datetime, timezone
    from io import StringIO
    from resource_coordinator.presentation import render_miner_status

    output = StringIO()
    render_miner_status({
        "status": "running", "name": "krig_miner", "pid": 73392,
        "owner": "coordinator", "is_coordinator_owned": True,
        "executable": r"C:\Program Files\krig-miner.exe",
        "create_time": datetime(2026, 11, 6, 14, 39, tzinfo=timezone.utc).timestamp(),
        "manual_override": False, "manual_override_until": None,
        "gpu_idle_condition": {}, "debug": {"nested": "must not flatten"},
    }, stream=output, color="never", width=80)
    rendered = output.getvalue()

    assert "Miner — krig_miner" in rendered
    assert "Process" in rendered and "Controls" in rendered
    assert "Ownership" in rendered and "Coordinator" in rendered
    assert "Manual hold" in rendered and "Inactive" in rendered
    assert "GPU-idle resume" in rendered and "Not configured" in rendered
    assert "Started" in rendered and "Nov 6, 2026" in rendered
    assert "create_time" not in rendered and "must not flatten" not in rendered
    assert "Manual override u" not in rendered


@pytest.mark.parametrize("width", [80, 100, 120])
def test_miner_status_renderer_keeps_operational_labels_at_common_widths(width):
    from io import StringIO
    from resource_coordinator.presentation import render_miner_status

    output = StringIO()
    render_miner_status({"status": "running", "name": "krig_miner", "pid": 1,
                         "is_coordinator_owned": True, "executable": "C:/" + ("deep/" * 40) + "krig.exe",
                         "create_time": 1793975984.0, "manual_override": False,
                         "manual_override_until": None, "gpu_idle_condition": {}},
                        stream=output, color="never", width=width)
    rendered = output.getvalue()
    assert "Manual hold" in rendered and "GPU-idle resume" in rendered
    assert "Started" in rendered and "Ownership" in rendered


def test_coordinator_status_renderer_does_not_claim_upstream_connected_or_duplicate_ready():
    from io import StringIO
    from resource_coordinator.presentation import render_coordinator_status

    output = StringIO()
    render_coordinator_status({
        "is_ready": True, "service_state": "ready", "listen_url": "127.0.0.1:1235",
        "upstream_url": "http://127.0.0.1:1234", "gpu_inference": {
            "active_count": 0, "pending_count": 0, "is_cooling_down": False,
            "is_restart_inhibited": False,
        }, "processes": {"krig_miner": {
            "state": "running", "pid": 73392, "is_coordinator_owned": True,
            "lifecycle_owner": "coordinator", "was_stopped_by_coordinator": False,
        }},
    }, stream=output, color="never", width=100)
    rendered = output.getvalue()
    assert "READY" in rendered
    assert "127.0.0.1:1235" in rendered and "127.0.0.1:1234" in rendered
    assert "connected" not in rendered.casefold()
    assert "Coordinator" in rendered
    assert "coordinator;" not in rendered
    assert "Ready: Yes" not in rendered


def test_upgrade_renderer_hides_internal_task_xml_and_journal_by_default():
    from io import StringIO
    from resource_coordinator.presentation import render_upgrade_result

    output = StringIO()
    render_upgrade_result({
        "status": "blocked", "phase": "PREFLIGHT", "blockers": ["Listener identity unavailable"],
        "source": {"version": "0.11.0", "revision": "abc"},
        "runtime": {"version": "0.10.0", "pid": 55},
        "task": {"name": "ResourceCoordinator-KRig-UserLogon"},
        "task_snapshot": {"definition": "<Task>secret xml</Task>"},
        "journal": {"requests": {"id": "raw durable journal"}},
        "elevation_required": True,
    }, stream=output, color="never", width=80)
    rendered = output.getvalue()
    assert "BLOCKED" in rendered and "Listener identity unavailable" in rendered
    assert "0.11.0" in rendered and "ResourceCoordinator-KRig-UserLogon" in rendered
    assert "secret xml" not in rendered and "raw durable journal" not in rendered
    assert "task_snapshot" not in rendered and "journal" not in rendered


def test_upgrade_plan_renderer_shows_source_task_and_elevation_without_preflight_dump():
    from io import StringIO
    from resource_coordinator.presentation import render_upgrade_result

    output = StringIO()
    render_upgrade_result({
        "status": "planned", "phase": "PREFLIGHT", "source_version": "0.11.1",
        "source_revision": "private-revision", "runtime_version": None, "runtime_legacy": True,
        "startup_task": "ResourceCoordinator-KRig-UserLogon", "elevation_required": True,
        "configured_gpu_settings": {"power_limit_w": 550.0}, "effective_gpu_settings": {"power_limit_w": 550.0},
        "changes": ["gracefully stop current coordinator and owned miner"],
    }, stream=output, color="never", width=80)
    rendered = output.getvalue()
    assert "0.11.1" in rendered and "Legacy installation" in rendered
    assert "ResourceCoordinator-KRig-UserLogon" in rendered and "Required" in rendered
    assert "private-revision" not in rendered and "gracefully stop" not in rendered


def test_specialized_renderer_json_remains_complete_and_redacted():
    from io import StringIO
    import json
    from resource_coordinator.presentation import render_miner_status

    output = StringIO()
    render_miner_status({"status": "stopped", "pid": None, "operator_token": "hidden",
                         "process_details": {"create_time": 123.0}}, as_json=True, stream=output)
    result = json.loads(output.getvalue())
    assert result["process_details"]["create_time"] == 123.0
    assert result["operator_token"] == "[REDACTED]"


def test_specialized_human_renderers_redact_secret_fields():
    from io import StringIO
    from resource_coordinator.presentation import render_miner_status

    output = StringIO()
    render_miner_status({"status": "stopped", "operator_token": "do-not-print", "reason": "normal"},
                        stream=output, color="never", width=80)
    assert "do-not-print" not in output.getvalue()


def test_health_and_startup_renderers_show_operational_summary_without_nested_dumps():
    from io import StringIO
    from resource_coordinator.presentation import render_health_result, render_startup_status

    health_output = StringIO()
    render_health_result({
        "status": "degraded", "service": {"service_state": "ready"}, "service_ready": True,
        "runtime_current": False, "credential_ready": True,
        "gpu": {"power_limit_w": 550.0, "memory_clock_mhz": 7001.0},
        "gpu_policy_verification": {"power_limit_w": "verified", "memory_clock_mhz": "verified"},
        "warnings": ["Runtime identity mismatch"], "runtime": {"revision": "opaque"},
        "credential": {"secret": "not for display"},
    }, stream=health_output, color="never", width=80)
    health = health_output.getvalue()
    assert "DEGRADED" in health and "Runtime identity" in health
    assert "550 W — verified" in health and "7001 MHz — verified" in health
    assert "opaque" not in health and "not for display" not in health

    startup_output = StringIO()
    render_startup_status({"authoritative": "ResourceCoordinator-KRig-UserLogon", "tasks": [{
        "name": "ResourceCoordinator-KRig-UserLogon", "mode": "logon", "enabled": True,
        "state": "Running", "run_level": "Highest", "action": "long internal command",
    }]}, stream=startup_output, color="never", width=80)
    startup = startup_output.getvalue()
    assert "Startup Tasks" in startup and "User logon" in startup
    assert "Enabled / Running" in startup and "Highest" in startup
    assert "long internal command" not in startup


def test_gaming_renderer_summarizes_saved_model_state():
    from io import StringIO
    from resource_coordinator.presentation import render_gaming_status

    output = StringIO()
    render_gaming_status({"status": "active", "state": "active", "miner_state": "stopped",
                          "models": {"model-id": {"temperature": 0.2}},
                          "reason": "Game session"}, stream=output, color="never", width=80)
    rendered = output.getvalue()
    assert "Gaming Mode" in rendered and "ACTIVE" in rendered
    assert "Miner" in rendered and "Stopped" in rendered
    assert "1 saved model settings (see --json)" in rendered
    assert "temperature" not in rendered


def test_health_renderer_does_not_call_partial_credentials_verified():
    from io import StringIO
    from resource_coordinator.presentation import render_health_result

    output = StringIO()
    render_health_result({"status": "degraded", "credential": {
        "credential_valid": True, "credential_file_readable": True, "acl_restricted": False,
    }, "runtime": {"version": "0.11.0"}}, stream=output, color="never", width=80)
    rendered = output.getvalue()
    assert "Credentials" in rendered and "Degraded" in rendered
    assert "Legacy / unverified" in rendered
    assert "Runtime identity" in rendered


def test_generic_renderer_summarizes_nested_objects_instead_of_flattening():
    from io import StringIO
    from resource_coordinator.presentation import render_result

    output = StringIO()
    render_result("Example", {"status": "ready", "process": {"name": "miner", "pid": 10}},
                  stream=output, color="never", width=80)
    rendered = output.getvalue()
    assert "2 structured fields (see --json)" in rendered
    assert "name: miner; pid: 10" not in rendered


@pytest.mark.parametrize(
    ("legacy", "canonical", "handler_name", "expected_command", "expected_action"),
    [
        (["miner", "pause", "-d", "2h"], ["control", "miner", "pause", "-d", "2h"],
         "cmd_miner", "miner", "pause"),
        (["gaming", "start"], ["control", "gaming", "on"],
         "cmd_gaming", "gaming", "start"),
        (["gaming", "stop"], ["control", "gaming", "off"],
         "cmd_gaming", "gaming", "stop"),
        (["restart"], ["service", "restart"], "cmd_lifecycle", "restart", None),
        (["upgrade"], ["system", "upgrade"], "_cmd_installation", "upgrade", None),
    ],
)
def test_main_dispatches_legacy_and_canonical_paths_to_same_handler(
    monkeypatch, legacy, canonical, handler_name, expected_command, expected_action
):
    import resource_coordinator.cli as cli

    seen = []

    def handler(args):
        seen.append(args)
        return 0

    monkeypatch.setattr(cli, handler_name, handler)
    for argv in (legacy, canonical):
        with pytest.raises(SystemExit) as raised:
            cli.main(argv)
        assert raised.value.code == 0

    assert len(seen) == 2
    assert [args.command for args in seen] == [expected_command, expected_command]
    assert seen[0].operation_id == seen[1].operation_id
    if expected_action:
        field = "gaming_command" if expected_command == "gaming" else "miner_command"
        assert getattr(seen[0], field) == getattr(seen[1], field) == expected_action


def test_service_restart_keeps_restart_endpoint_and_json_stdout(monkeypatch, capsys):
    from unittest.mock import MagicMock
    import httpx
    import resource_coordinator.cli as cli

    monkeypatch.setenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", "test-token")
    response = MagicMock(status_code=202)
    response.json.return_value = {"status": "draining"}
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = response
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: client)

    with pytest.raises(SystemExit) as raised:
        cli.main(["service", "restart", "--json"])

    assert raised.value.code == 0
    assert client.post.call_args.args[0] == "http://127.0.0.1:1235/_coordinator/restart"
    import json
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"status": "draining"}
    assert "HTTP Request" not in captured.out + captured.err


def test_credential_diagnostics_render_human_summary_without_secret(monkeypatch, capsys):
    import resource_coordinator.cli as cli

    monkeypatch.setattr(cli, "credential_doctor", lambda: {
        "credential_valid": True,
        "credential_file_readable": True,
        "acl_restricted": True,
        "environment_override_matches_file": True,
        "operator_token": "must-not-appear",
    })
    args = parse_args(["system", "auth", "doctor"])

    assert cli.cmd_auth(args) == 0
    output = capsys.readouterr().out
    assert "Operator Credentials" in output
    assert "Credential valid" in output
    assert "must-not-appear" not in output


def test_unhandled_command_error_returns_clean_json_and_nonzero_status(monkeypatch, capsys):
    import json
    import resource_coordinator.cli as cli

    def fail(_args):
        raise RuntimeError("fixture failure")

    monkeypatch.setattr(cli, "cmd_status", fail)
    with pytest.raises(SystemExit) as raised:
        cli.main(["status", "--json"])

    assert raised.value.code == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "status": "error", "operation": "status", "message": "fixture failure"
    }
    assert "Traceback" not in captured.err


def test_log_follow_handler_preserves_raw_output_bytes(monkeypatch):
    from io import BytesIO
    from unittest.mock import patch

    import resource_coordinator.cli as cli

    class Output:
        def __init__(self):
            self.buffer = BytesIO()

        def flush(self):
            pass

    class Response:
        status_code = 200
        content = b"\x1b[31mraw miner output\x1b[0m\r\n"
        headers = {"x-log-offset": str(len(content))}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, *_args, **_kwargs):
            return Response()

    output = Output()
    monkeypatch.setenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", "test-token")
    monkeypatch.setattr(cli.httpx, "AsyncClient", lambda **_kwargs: Client())
    args = parse_args(["logs", "krig_miner"])
    with patch.object(cli.sys, "stdout", output):
        assert cli.cmd_logs(args) == 0
    assert output.buffer.getvalue() == Response.content
