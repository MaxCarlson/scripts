import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace


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
