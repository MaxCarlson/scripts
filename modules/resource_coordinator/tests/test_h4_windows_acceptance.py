import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).parents[1] / "tools" / "h4_qualification" / "windows_acceptance.py"
SPEC = importlib.util.spec_from_file_location("h4_windows_acceptance", MODULE_PATH)
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


def guest_evidence(**overrides):
    value = {
        "queries": {"system": "available", "tasks": "available", "services": "available",
                    "processes": "available"},
        "computer": {"manufacturer": "Microsoft Corporation", "model": "Virtual Machine",
                     "hypervisor_present": True},
        "rc_tasks": [], "rc_services": [], "rc_processes": [],
    }
    value.update(overrides)
    return value


def test_virtual_guest_identity_uses_observed_system_metadata():
    assert harness.guest_identity(guest_evidence())
    host = guest_evidence(computer={"manufacturer": "Gigabyte", "model": "X870E", "hypervisor_present": True})
    assert not harness.guest_identity(host)


def test_runner_cli_supports_short_and_long_options(tmp_path):
    short = harness.build_parser().parse_args([
        "-r", str(tmp_path), "-a", "-p", "task", "-A", harness.AUTHORIZATION_PHRASE, "-T", "60", "-j",
    ])
    long = harness.build_parser().parse_args([
        "--test-root", str(tmp_path), "--apply", "--profile", "task", "--authorization",
        harness.AUTHORIZATION_PHRASE, "--timeout-seconds", "60", "--json",
    ])
    assert short.profile == long.profile == "task"
    assert short.authorization == long.authorization == harness.AUTHORIZATION_PHRASE
    assert short.timeout_seconds == long.timeout_seconds == 60


def test_task_and_process_inventory_failure_fails_closed(tmp_path):
    evidence = guest_evidence(queries={"system": "available", "tasks": "error", "services": "available",
                                       "processes": "available"})
    reasons = harness.guard_reasons(evidence, tmp_path / "h4-rc-test", is_windows=True)
    assert "tasks_inventory_unavailable" in reasons


def test_existing_production_task_or_rc_process_blocks_guest_mutation(tmp_path):
    evidence = guest_evidence(rc_tasks=[{"name": "ResourceCoordinator-KRig-UserLogon"}])
    reasons = harness.guard_reasons(evidence, tmp_path / "h4-rc-test", is_windows=True)
    assert "rc_task_present" in reasons
    evidence = guest_evidence(rc_processes=[{"name": "krig-miner.exe", "pid": 45}])
    assert "rc_or_miner_process_present" in harness.guard_reasons(
        evidence, tmp_path / "h4-rc-test", is_windows=True
    )


def test_preflight_writes_artifacts_but_refuses_primary_host(tmp_path):
    root = tmp_path / "h4-rc-run"
    root.mkdir()
    host = guest_evidence(computer={"manufacturer": "Gigabyte", "model": "X870E", "hypervisor_present": True})
    result = harness.main(["--test-root", str(root), "--json"], evidence_override=host, is_windows=True)
    assert result == 3
    preflight = json.loads((root / "preflight.json").read_text(encoding="utf-8"))
    assert preflight["guest_verified"] is False
    assert preflight["mutation_ready"] is False
    assert json.loads((root / "test-results.json").read_text(encoding="utf-8"))["status"] == "not_run"
    assert (root / "upgrade-receipts").is_dir()
    assert (root / "task-snapshots").is_dir()


def test_task_profile_without_apply_is_only_a_preflight():
    with TemporaryDirectory(prefix="h4-rc-task-preflight-") as temp:
        root = Path(temp)
        result = harness.main(["--test-root", str(root), "--profile", "task", "--json"],
                              evidence_override=guest_evidence(), is_windows=True)
        assert result == 0
        preflight = json.loads((root / "preflight.json").read_text(encoding="utf-8"))
        assert preflight["apply_requested"] is False
        assert preflight["mutation_ready"] is True
        assert not list(root.glob("junit-*.xml"))


def test_mutating_profile_requires_affirmative_authorization(tmp_path):
    root = tmp_path / "h4-rc-run"
    root.mkdir()
    assert harness.main(["--test-root", str(root), "--profile", "task", "--apply"],
                        evidence_override=guest_evidence(), is_windows=True) == 2


def test_full_lifecycle_profiles_default_to_read_only_preflight():
    parser = harness.build_parser()
    assert parser.parse_args(["-r", "C:/h4-rc-test"]).profile == "preflight"
    for profile in ("install", "upgrade", "rollback", "full", "cleanup"):
        assert parser.parse_args(["-r", "C:/h4-rc-test", "-p", profile]).apply is False
    for stage in harness.FAULT_STAGES:
        assert parser.parse_args(["-r", "C:/h4-rc-test", "-p", "rollback", "-F", stage]).fault_stage == stage


def test_guard_allows_only_exact_test_owned_task_and_process(tmp_path):
    root = tmp_path / "h4-rc-test"
    task_name = "ResourceCoordinator-H4-run-logon"
    process = {"name": "python.exe", "pid": 120, "creation_time": 1000.5,
               "executable_path": "C:/Python/python.exe"}
    evidence = guest_evidence(
        rc_tasks=[{"name": task_name, "state": "Ready", "test_root_action": True}],
        rc_processes=[process],
    )
    reasons = harness.guard_reasons(
        evidence, root, is_windows=True, owned_task_names=[task_name],
        owned_processes=[{"pid": 120, "creation_time": 1001.0,
                          "executable_path": "c:/python/python.exe"}],
    )
    assert "rc_task_present" not in reasons
    assert "rc_or_miner_process_present" not in reasons
    evidence["rc_tasks"][0]["test_root_action"] = False
    assert "rc_task_present" in harness.guard_reasons(
        evidence, root, is_windows=True, owned_task_names=[task_name]
    )


def test_guest_listener_guard_requires_exact_owned_process_identity(tmp_path):
    process = {"pid": 120, "creation_time": 1000.5, "executable_path": "C:/Python/python.exe"}
    evidence = guest_evidence(
        listener_port=45431, listener_rows=[{"port": 45431, **process}],
        queries={"system": "available", "tasks": "available", "services": "available",
                 "processes": "available", "listener": "available"},
    )
    assert "listener_port_owner_unverified" in harness.guard_reasons(
        evidence, tmp_path / "h4-rc-run", is_windows=True
    )
    assert "listener_port_owner_unverified" not in harness.guard_reasons(
        evidence, tmp_path / "h4-rc-run", is_windows=True, owned_processes=[process]
    )
    evidence["queries"]["listener"] = "error"
    assert "listener_inventory_unavailable" in harness.guard_reasons(
        evidence, tmp_path / "h4-rc-run", is_windows=True, owned_processes=[process]
    )


def test_listener_probe_is_loopback_scoped_and_bounded(monkeypatch):
    captured = {}
    monkeypatch.setattr(harness, "_which", lambda _name: "powershell.exe")

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["timeout"] = kwargs["timeout"]
        captured["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout='{"queries":{"listener":"available"}}', stderr="")

    monkeypatch.setattr(harness.subprocess, "run", fake_run)
    result = harness._run_powershell(listener_port=45431)
    assert result["queries"]["listener"] == "available"
    assert captured["timeout"] == 20
    assert captured["env"]["RC_H4_LISTENER_PORT"] == "45431"
    script = captured["command"][-1]
    assert "Get-NetTCPConnection -State Listen -LocalPort $port" in script
    assert "Get-CimInstance Win32_Process" in script


def test_guest_mutation_requires_independent_env_authorization(tmp_path, monkeypatch):
    root = tmp_path / "h4-rc-run"
    root.mkdir()
    monkeypatch.delenv("RC_H4_DISPOSABLE_GUEST_AUTHORIZED", raising=False)
    result = harness.main([
        "-r", str(root), "-a", "-p", "install", "-G", "-A", harness.AUTHORIZATION_PHRASE,
    ], evidence_override=guest_evidence(), is_windows=True)
    assert result == 2


def test_offline_apply_runs_scoped_test_profile_without_guest_mutation(tmp_path, monkeypatch):
    root = tmp_path / "h4-rc-run"
    root.mkdir()
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        junit = Path(command[command.index("--junitxml") + 1])
        junit.write_text('<testsuites><testsuite tests="3" failures="0" errors="0" skipped="0"/></testsuites>',
                         encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="pytest output\n", stderr="")

    monkeypatch.setattr(harness.subprocess, "run", fake_run)
    host = guest_evidence(computer={"manufacturer": "Gigabyte", "model": "X870E", "hypervisor_present": True},
                          rc_tasks=[{"name": "ResourceCoordinator-KRig-UserLogon"}])
    result = harness.main([
        "--test-root", str(root), "--apply", "--profile", "offline",
        "--authorization", harness.AUTHORIZATION_PHRASE, "--json",
    ], evidence_override=host,
       is_windows=True)
    assert result == 0
    assert "tests/test_installation.py" in captured["command"]
    assert "RC_WINDOWS_TASK_INTEGRATION" not in captured["env"]
    assert json.loads((root / "test-results.json").read_text(encoding="utf-8"))["status"] == "passed"
    preflight = json.loads((root / "preflight.json").read_text(encoding="utf-8"))
    assert preflight["guest_verified"] is False
    assert preflight["mutation_ready"] is False


def test_cleanup_manifest_keeps_every_lifecycle_phase_and_rejects_duplicates(tmp_path):
    root = tmp_path / "h4-rc-run"
    root.mkdir()
    for phase in ("install", "upgrade", "rollback"):
        phase_root = root / "runs" / phase
        phase_root.mkdir(parents=True)
        harness._append_cleanup_manifest(root, {
            "schema_version": 1,
            "phase": phase,
            "root": str(phase_root),
            "task_names": [f"ResourceCoordinator-H4-run-{phase}-{mode}" for mode in ("boot", "logon", "viewer")],
            "port": 24000 + len(phase),
        })

    manifests = harness._load_cleanup_manifests(root)
    assert [item["phase"] for item in manifests] == ["install", "upgrade", "rollback"]
    assert len({name for item in manifests for name in item["task_names"]}) == 9

    duplicate = dict(manifests[0])
    with pytest.raises(RuntimeError, match="duplicate cleanup task identity"):
        harness._append_cleanup_manifest(root, duplicate)
