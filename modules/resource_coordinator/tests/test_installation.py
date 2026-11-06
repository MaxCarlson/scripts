import base64
import json
import re
import sys
from pathlib import Path

import pytest

from resource_coordinator.installation import (
    InstallationError,
    InstallationPaths,
    ManagedInstallation,
    StartupTask,
    TASK_NAMES,
    TASK_MARKER,
    _clean_powershell_error,
    WindowsStartupTaskBackend,
)
from resource_coordinator.cli import parse_args


class MemoryTasks:
    def __init__(self):
        self.items = {}
        self.install_calls = []
        self.start_calls = []

    def status(self):
        return list(self.items.values())

    def install(self, mode, launcher, *, non_interactive=False):
        self.install_calls.append((mode, launcher, non_interactive))
        name = f"ResourceCoordinator-KRig-{mode.title()}"
        task = StartupTask(name, mode, False, "Ready", "mcarls", "Highest", str(launcher), True)
        self.items[name] = task
        return task

    def install_viewer(self, launcher):
        task = StartupTask("KRig-Live-Output-Viewer", "viewer", False, "Ready", "mcarls", "Limited", str(launcher), True)
        self.items[task.name] = task
        return task

    def set_enabled(self, task, enabled, *, non_interactive=False):
        updated = StartupTask(task.name, task.mode, enabled, "Ready", task.user_id, task.run_level, task.action, task.owned)
        self.items[task.name] = updated
        return updated

    def uninstall(self, task, *, non_interactive=False):
        self.items.pop(task.name, None)

    def start(self, task, *, non_interactive=False):
        self.start_calls.append(task.name)

    def snapshot(self, task):
        assert task.owned
        return {"definition": f"<Task name='{task.name}' />", "enabled": task.enabled}

    def restore_snapshot(self, task, snapshot, *, non_interactive=False):
        self.items[task.name] = task


def make_paths(tmp_path: Path):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    template = repo / "modules" / "resource_coordinator" / "config.production-template.yaml"
    template.parent.mkdir(parents=True)
    template.write_text("version: '1.0'\nprocesses: {}\npolicies: []\n", encoding="utf-8")
    package = repo / "modules" / "resource_coordinator" / "resource_coordinator"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("__version__ = '0.10.0'\n", encoding="utf-8")
    paths = InstallationPaths.discover(home=home, repository=repo, python=Path(sys.executable))
    return paths, template


def _secure_credential_report():
    return {
        "credential_file_exists": True,
        "credential_file_readable": True,
        "credential_valid": True,
        "acl_restricted": True,
        "environment_override_matches_file": None,
    }


def _write_offline_journal(paths: InstallationPaths, *, requests: str = "") -> Path:
    state_path = paths.root / "coordinator_state.json"
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.config.write_text(
        f"version: '1.0'\nservice:\n  state_persistence_path: '{state_path}'\nprocesses: {{}}\npolicies: []\n",
        encoding="utf-8",
    )
    from resource_coordinator.core.durable_state import StateCodec

    StateCodec.initialize(state_path)
    if requests:
        request_id, phase = requests.split(":", 1)
        StateCodec.record_request_phase(state_path, request_id, "gpu.inference", phase)
    return state_path


def test_setup_without_apply_is_a_plan_and_does_not_create_files(tmp_path):
    paths, template = make_paths(tmp_path)
    tasks = MemoryTasks()
    manager = ManagedInstallation(paths, tasks, template=template)
    manager._service_status = lambda: None
    manager._wait_for_service = lambda timeout=30.0: {"service_state": "ready"}

    result = manager.setup(apply=False, mode="logon")

    assert result["status"] == "planned"
    assert result["mode"] == "logon"
    assert not paths.root.exists()
    assert tasks.install_calls == []


def test_upgrade_cli_defaults_to_preview_and_supports_apply_json_and_non_interactive():
    preview = parse_args(["upgrade"])
    apply = parse_args(["upgrade", "-a", "-j", "-n"])

    assert preview.command == "upgrade"
    assert preview.apply is False
    assert preview.json is False
    assert preview.non_interactive is False
    assert apply.command == "upgrade"
    assert apply.apply is True
    assert apply.json is True
    assert apply.non_interactive is True


def test_upgrade_preview_is_read_only_and_reports_legacy_runtime(tmp_path, monkeypatch):
    import resource_coordinator.installation as installation_module

    paths, _ = make_paths(tmp_path)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.config.write_text(
        f"version: '1.0'\nservice:\n  state_persistence_path: '{paths.state}'\nprocesses: {{}}\npolicies: []\n",
        encoding="utf-8",
    )
    from resource_coordinator.core.durable_state import StateCodec
    StateCodec.initialize(paths.state)
    task = StartupTask(
        TASK_NAMES["logon"], "logon", True, "Ready", "mcarls", "Highest",
        f'powershell.exe -File "{paths.root / "start-coordinator.ps1"}"', True,
    )
    tasks = MemoryTasks()
    tasks.items[task.name] = task
    manager = ManagedInstallation(paths, tasks)
    manager._service_status = lambda: {
        "service_state": "ready", "runtime": {"pid": 51, "stop_miner_on_shutdown": True},
        "gpu_inference": {"active_count": 0, "pending_count": 0, "is_restart_inhibited": False},
        "processes": {},
    }
    monkeypatch.setattr(installation_module, "_listener_identity", lambda: {"pid": 51, "create_time": 10.0})
    monkeypatch.setattr(installation_module, "_effective_gpu_settings", lambda: None)
    monkeypatch.setattr(installation_module, "load_token", lambda: "test-token")
    monkeypatch.setattr(installation_module, "credential_doctor", lambda: _secure_credential_report())

    result = manager.upgrade()

    assert result["status"] == "planned"
    assert result["runtime_legacy"] is True
    assert result["will_drain_inference"] is True
    assert not paths.upgrade_receipt.exists()
    assert not paths.upgrade_policy.exists()
    assert tasks.install_calls == []
    assert tasks.start_calls == []

    tasks._admin = lambda: False
    noninteractive = manager.upgrade(apply=True, non_interactive=True)
    assert noninteractive["status"] == "blocked"
    assert any("non-interactive mode forbids UAC" in item for item in noninteractive["preflight"]["blockers"])
    assert not paths.upgrade_receipt.exists()


def test_upgrade_noop_when_runtime_fingerprint_and_managed_launcher_match(tmp_path, monkeypatch):
    import resource_coordinator.installation as installation_module

    paths, _ = make_paths(tmp_path)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.config.write_text(
        f"version: '1.0'\nservice:\n  state_persistence_path: '{paths.state}'\nprocesses: {{}}\npolicies: []\n",
        encoding="utf-8",
    )
    from resource_coordinator.core.durable_state import StateCodec
    StateCodec.initialize(paths.state)
    task = StartupTask(TASK_NAMES["logon"], "logon", True, "Ready", "mcarls", "Highest",
                       f'powershell.exe -File "{paths.launcher}"', True)
    tasks = MemoryTasks()
    tasks.items[task.name] = task
    manager = ManagedInstallation(paths, tasks)
    identity = {"version": "0.10.0", "source_path": str(paths.repository / "modules/resource_coordinator/resource_coordinator/__init__.py"),
                "revision": "same-source"}
    monkeypatch.setattr(installation_module, "build_runtime_identity", lambda package: identity)
    manager._service_status = lambda: {
        "service_state": "ready", "runtime": {**identity, "pid": 51},
        "gpu_inference": {"active_count": 0, "pending_count": 0, "is_restart_inhibited": False},
        "processes": {},
    }
    monkeypatch.setattr(installation_module, "_listener_identity", lambda: {"pid": 51, "create_time": 10.0})
    monkeypatch.setattr(installation_module, "_effective_gpu_settings", lambda: None)
    monkeypatch.setattr(installation_module, "load_token", lambda: "test-token")
    monkeypatch.setattr(installation_module, "credential_doctor", lambda: _secure_credential_report())

    result = manager.upgrade(apply=True)

    assert result["status"] == "already-current"
    assert result["phase"] == "VERIFIED"
    assert tasks.install_calls == []
    assert tasks.start_calls == []
    assert not paths.upgrade_receipt.exists()

    manager._service_status = lambda: {
        "service_state": "ready", "runtime": {**identity, "revision": "previous-source-revision", "pid": 51},
        "gpu_inference": {"active_count": 0, "pending_count": 0, "is_restart_inhibited": False},
        "processes": {},
    }
    changed_source = manager.upgrade()
    assert changed_source["status"] == "planned"
    assert changed_source["runtime_revision"] == "previous-source-revision"
    assert changed_source["source_revision"] == "same-source"


def test_upgrade_shutdown_rejection_restores_prepared_launcher_and_leaves_task_untouched(tmp_path, monkeypatch):
    import resource_coordinator.installation as installation_module

    paths, _ = make_paths(tmp_path)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.config.write_text(
        f"version: '1.0'\nservice:\n  state_persistence_path: '{paths.state}'\nprocesses: {{}}\npolicies: []\n",
        encoding="utf-8",
    )
    from resource_coordinator.core.durable_state import StateCodec
    StateCodec.initialize(paths.state)
    task = StartupTask(TASK_NAMES["logon"], "logon", True, "Ready", "mcarls", "Highest",
                       f'powershell.exe -File "{paths.root / "start-coordinator.ps1"}"', True)
    tasks = MemoryTasks()
    tasks.items[task.name] = task
    manager = ManagedInstallation(paths, tasks)
    manager._service_status = lambda: {
        "service_state": "ready", "runtime": {"pid": 51},
        "gpu_inference": {"active_count": 0, "pending_count": 0, "is_restart_inhibited": False},
        "processes": {},
    }
    monkeypatch.setattr(installation_module, "_listener_identity", lambda: {"pid": 51, "create_time": 10.0})
    monkeypatch.setattr(installation_module, "_effective_gpu_settings", lambda: None)
    monkeypatch.setattr(installation_module, "load_token", lambda: "test-token")
    monkeypatch.setattr(installation_module, "credential_doctor", lambda: _secure_credential_report())
    monkeypatch.setattr(installation_module.ManagedInstallation, "_request_graceful_shutdown",
                        lambda self, token: type("Response", (), {"status_code": 404})())

    with pytest.raises(InstallationError, match="not accepted"):
        manager.upgrade(apply=True)

    assert not paths.launcher.exists()
    assert not paths.upgrade_policy.exists()
    assert tasks.install_calls == []
    assert tasks.start_calls == []
    receipt = json.loads(paths.upgrade_receipt.read_text(encoding="utf-8"))
    assert receipt["phase"] == "RECOVERY_REQUIRED"
    assert receipt["failed_at"] == "DRAINING"


def test_upgrade_preserves_manual_miner_hold_while_verifying_new_runtime(tmp_path, monkeypatch):
    import resource_coordinator.installation as installation_module

    paths, _ = make_paths(tmp_path)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.config.write_text(
        f"version: '1.0'\nservice:\n  state_persistence_path: '{paths.state}'\nprocesses:\n"
        "  krig_miner:\n    backend: fake\n    executable: C:/Mining/krig-miner.exe\n"
        "    arguments: ['--user', 'wallet/worker']\npolicies: []\n",
        encoding="utf-8",
    )
    from resource_coordinator.core.durable_state import StateCodec
    StateCodec.initialize(paths.state)
    from resource_coordinator.core.durable_state import PersistedProcess
    durable_state = StateCodec.load(paths.state)
    durable_state.processes["krig_miner"] = PersistedProcess(
        name="krig_miner", is_manual_override=True, lifecycle_owner="coordinator"
    )
    StateCodec.save_atomic(durable_state, paths.state)
    task = StartupTask(TASK_NAMES["logon"], "logon", True, "Ready", "mcarls", "Highest",
                       f'powershell.exe -File "{paths.root / "start-coordinator.ps1"}"', True)
    tasks = MemoryTasks()
    tasks.items[task.name] = task
    manager = ManagedInstallation(paths, tasks)
    runtime_identity = {
        "version": "0.10.0",
        "source_path": str(paths.repository / "modules/resource_coordinator/resource_coordinator/__init__.py"),
        "revision": "new-revision",
    }
    old_service = {
        "service_state": "ready", "runtime": {"pid": 51, "stop_miner_on_shutdown": True},
        "gpu_inference": {"active_count": 0, "pending_count": 0, "is_restart_inhibited": False},
        "processes": {"krig_miner": {"name": "krig_miner", "state": "running",
                                      "is_coordinator_owned": True, "pid": 91, "create_time": 30.0}},
    }
    statuses = iter([old_service, None, None])
    manager._service_status = lambda: next(statuses)
    new_service = {
        "service_state": "ready", "runtime": {**runtime_identity, "pid": 52},
        "upstream_url": "http://127.0.0.1:1234",
        "processes": {"krig_miner": {"name": "krig_miner", "state": "stopped",
                                      "is_coordinator_owned": False}},
    }
    manager._wait_for_service = lambda timeout=30.0: new_service
    monkeypatch.setattr(installation_module, "build_runtime_identity", lambda package: runtime_identity)
    monkeypatch.setattr(installation_module, "_exact_process_is_alive", lambda pid, created: False)
    monkeypatch.setattr(installation_module.ManagedInstallation, "_coordinator_port_open", staticmethod(lambda: False))
    monkeypatch.setattr(installation_module, "_effective_gpu_settings", lambda: None)
    listener_identities = iter([
        {"pid": 51, "create_time": 10.0},
        {"pid": 52, "create_time": 20.0},
    ])
    monkeypatch.setattr(installation_module, "_listener_identity", lambda: next(listener_identities))
    monkeypatch.setattr(installation_module, "_effective_gpu_settings", lambda: {"power_limit_w": 550.0})
    monkeypatch.setattr(installation_module, "load_token", lambda: "test-token")
    monkeypatch.setattr(installation_module, "credential_doctor", lambda: _secure_credential_report())
    monkeypatch.setattr(installation_module.ManagedInstallation, "_request_graceful_shutdown",
                        staticmethod(lambda token: type("Response", (), {"status_code": 202})()))
    resume_calls = []
    monkeypatch.setattr(installation_module.httpx, "post",
                        lambda *args, **kwargs: resume_calls.append((args, kwargs)) or
                        type("Response", (), {"status_code": 200})())

    class ControlClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def get(self, *_args, **_kwargs):
            return type("Response", (), {"status_code": 200})()

    monkeypatch.setattr(installation_module.httpx, "Client", ControlClient)

    result = manager.upgrade(apply=True, timeout=0.1)

    assert result["status"] == "verified"
    assert result["runtime"]["revision"] == "new-revision"
    assert tasks.install_calls == [("logon", paths.launcher, False)]
    assert tasks.start_calls == ["ResourceCoordinator-KRig-Logon"]
    assert resume_calls == []
    receipt = json.loads(paths.upgrade_receipt.read_text(encoding="utf-8"))
    assert receipt["phase"] == "VERIFIED"


def test_interrupted_upgrade_retries_only_after_old_owner_and_lock_are_gone(tmp_path, monkeypatch):
    import resource_coordinator.installation as installation_module

    paths, _ = make_paths(tmp_path)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.config.write_text(
        f"version: '1.0'\nservice:\n  state_persistence_path: '{paths.state}'\nprocesses: {{}}\npolicies: []\n",
        encoding="utf-8",
    )
    from resource_coordinator.core.durable_state import StateCodec
    StateCodec.initialize(paths.state)
    task = StartupTask(TASK_NAMES["logon"], "logon", True, "Ready", "mcarls", "Highest",
                       f'powershell.exe -File "{paths.root / "start-coordinator.ps1"}"', True)
    tasks = MemoryTasks()
    tasks.items[task.name] = task
    manager = ManagedInstallation(paths, tasks)
    runtime_identity = {
        "version": "0.10.0",
        "source_path": str(paths.repository / "modules/resource_coordinator/resource_coordinator/__init__.py"),
        "revision": "retry-revision",
    }
    new_service = {"service_state": "ready", "runtime": {**runtime_identity, "pid": 52},
                   "upstream_url": "http://127.0.0.1:1234", "processes": {}}
    manager._service_status = lambda: None
    manager._wait_for_service = lambda timeout=30.0: new_service
    monkeypatch.setattr(installation_module, "build_runtime_identity", lambda package: runtime_identity)
    listener_results = iter([None, None, {"pid": 52, "create_time": 20.0}])
    monkeypatch.setattr(installation_module, "_listener_identity", lambda: next(listener_results))
    monkeypatch.setattr(installation_module.ManagedInstallation, "_coordinator_port_open", staticmethod(lambda: False))
    monkeypatch.setattr(installation_module, "_exact_process_is_alive", lambda pid, created: False)
    monkeypatch.setattr(installation_module, "_effective_gpu_settings", lambda: None)
    monkeypatch.setattr(installation_module, "load_token", lambda: "test-token")
    monkeypatch.setattr(installation_module, "credential_doctor", lambda: _secure_credential_report())

    class ControlClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def get(self, *_args, **_kwargs):
            return type("Response", (), {"status_code": 200})()

    monkeypatch.setattr(installation_module.httpx, "Client", ControlClient)
    paths.upgrade_receipt.write_text(json.dumps({
        "schema": 1,
        "phase": "RECOVERY_REQUIRED",
        "failed_at": "DRAINING",
        "source": runtime_identity,
        "old_service_pid": 51,
        "old_service_create_time": 10.0,
        "old_miner": {},
        "miner_was_running": False,
        "miner_resume_allowed": False,
        "configured_gpu_settings": {},
        "task_snapshot": {"definition": "<Task />", "enabled": True},
    }), encoding="utf-8")

    result = manager.upgrade(apply=True)

    assert result["status"] == "verified"
    assert result["recovered"] is True
    assert tasks.start_calls == ["ResourceCoordinator-KRig-Logon"]
    assert json.loads(paths.upgrade_receipt.read_text(encoding="utf-8"))["phase"] == "VERIFIED"


def test_upgrade_never_starts_replacement_while_original_miner_pid_is_alive(tmp_path, monkeypatch):
    import resource_coordinator.installation as installation_module

    paths, _ = make_paths(tmp_path)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.config.write_text(
        f"version: '1.0'\nservice:\n  state_persistence_path: '{paths.state}'\nprocesses:\n"
        "  krig_miner:\n    backend: fake\n    executable: C:/Mining/krig-miner.exe\n"
        "    arguments: ['--user', 'wallet/worker']\npolicies: []\n",
        encoding="utf-8",
    )
    from resource_coordinator.core.durable_state import StateCodec
    StateCodec.initialize(paths.state)
    task = StartupTask(TASK_NAMES["logon"], "logon", True, "Ready", "mcarls", "Highest",
                       f'powershell.exe -File "{paths.root / "start-coordinator.ps1"}"', True)
    tasks = MemoryTasks()
    tasks.items[task.name] = task
    manager = ManagedInstallation(paths, tasks)
    old_service = {
        "service_state": "ready", "runtime": {"pid": 51, "stop_miner_on_shutdown": True},
        "gpu_inference": {"active_count": 0, "pending_count": 0, "is_restart_inhibited": False},
        "processes": {"krig_miner": {"name": "krig_miner", "state": "running",
                                      "is_coordinator_owned": True, "pid": 91, "create_time": 30.0}},
    }
    statuses = iter([old_service, None])
    manager._service_status = lambda: next(statuses)
    monkeypatch.setattr(installation_module, "_listener_identity",
                        lambda: {"pid": 51, "create_time": 10.0})
    monkeypatch.setattr(installation_module.ManagedInstallation, "_coordinator_port_open", staticmethod(lambda: False))
    monkeypatch.setattr(installation_module, "_exact_process_is_alive",
                        lambda pid, created: pid == 91)
    monkeypatch.setattr(installation_module, "_effective_gpu_settings", lambda: {"power_limit_w": 550.0})
    monkeypatch.setattr(installation_module, "load_token", lambda: "test-token")
    monkeypatch.setattr(installation_module, "credential_doctor", lambda: _secure_credential_report())
    monkeypatch.setattr(installation_module.ManagedInstallation, "_request_graceful_shutdown",
                        staticmethod(lambda token: type("Response", (), {"status_code": 202})()))

    with pytest.raises(InstallationError, match="Original coordinator-owned miner is still running"):
        manager.upgrade(apply=True, timeout=0.1)

    assert tasks.install_calls == []
    assert tasks.start_calls == []
    assert not paths.upgrade_policy.exists()
    receipt = json.loads(paths.upgrade_receipt.read_text(encoding="utf-8"))
    assert receipt["phase"] == "RECOVERY_REQUIRED"
    assert receipt["failed_at"] == "DRAINING"


def test_ready_gpu_recovery_resumes_only_the_prior_coordinator_owned_miner(tmp_path, monkeypatch):
    import resource_coordinator.installation as installation_module

    paths, _ = make_paths(tmp_path)
    tasks = MemoryTasks()
    manager = ManagedInstallation(paths, tasks)
    runtime = {"version": "0.10.0", "source_path": "C:/source/__init__.py", "revision": "new"}
    miner_stopped = {"state": "stopped", "is_coordinator_owned": False}
    service = {
        "service_state": "ready", "runtime": runtime, "upstream_url": "http://127.0.0.1:1234",
        "gpu_inference": {"active_count": 0, "pending_count": 0, "is_restart_inhibited": False},
        "processes": {"krig_miner": miner_stopped},
    }
    service_after_resume = {
        **service,
        "processes": {"krig_miner": {"state": "running", "is_coordinator_owned": True, "pid": 83}},
    }
    paths.upgrade_receipt.parent.mkdir(parents=True, exist_ok=True)
    paths.upgrade_receipt.write_text(json.dumps({
        "phase": "RECOVERY_REQUIRED", "failed_at": "NEW_READY", "miner_resume_allowed": True,
        "configured_gpu_settings": {"power_limit_w": 550.0},
    }), encoding="utf-8")
    manager._service_status = lambda: service_after_resume
    monkeypatch.setattr(installation_module, "_effective_gpu_settings", lambda: {"power_limit_w": 550.0})
    monkeypatch.setattr(installation_module, "load_token", lambda: "test-token")
    monkeypatch.setattr(installation_module.httpx, "post",
                        lambda *args, **kwargs: type("Response", (), {"status_code": 200})())

    class ControlClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def get(self, *_args, **_kwargs):
            return type("Response", (), {"status_code": 200})()

    monkeypatch.setattr(installation_module.httpx, "Client", ControlClient)
    result = manager._finalize_ready_upgrade({
        "service": service, "runtime_current": True,
        "configured_upstream_url": "http://127.0.0.1:1234",
        "miner_name": "krig_miner", "miner_manual_hold": False,
    })

    assert result["status"] == "verified"
    assert result["recovered"] is True
    assert json.loads(paths.upgrade_receipt.read_text(encoding="utf-8"))["phase"] == "VERIFIED"


def test_powershell_clixml_error_is_rendered_as_actionable_plain_text():
    message = _clean_powershell_error(
        '#< CLIXML\n<S S="Error">Exception calling "ProcessRecord": "Access to a CIM resource was not available to the client."</S>'
    )

    assert message == "Access to a CIM resource was not available to the client."


def test_task_helper_uses_calling_users_root_and_identity_instead_of_elevated_profile(tmp_path):
    backend = WindowsStartupTaskBackend(managed_root=tmp_path / ".resource_coordinator",
                                        interactive_user="EXAMPLE\\mcarls")
    script = backend._script({"operation": "status"})

    assert "Get-RcSid ([string]$payload.interactive_user)" in script
    assert "$managedRoot = [IO.Path]::GetFullPath([string]$payload.managed_root)" in script
    assert "$env:USERPROFILE" not in script
    encoded_payload = re.search(r"FromBase64String\('([A-Za-z0-9+/=]+)'\)", script).group(1)
    payload = json.loads(base64.b64decode(encoded_payload))
    assert payload["managed_root"] == str((tmp_path / ".resource_coordinator").resolve())
    assert payload["interactive_user"] == "EXAMPLE\\mcarls"


def test_task_helper_snapshots_and_restores_exact_owned_task_definition(tmp_path):
    backend = WindowsStartupTaskBackend(managed_root=tmp_path / ".resource_coordinator",
                                        interactive_user="EXAMPLE\\mcarls")
    snapshot_script = backend._script({"operation": "snapshot", "task_name": TASK_NAMES["logon"]})
    restore_script = backend._script({"operation": "restore", "task_name": TASK_NAMES["logon"],
                                       "definition": "<Task />", "enabled": True})

    assert "Export-ScheduledTask" in snapshot_script
    assert "Test-RcOwned $existing" in snapshot_script
    assert "Register-ScheduledTask -TaskName $name -Xml" in restore_script
    assert "Enable-ScheduledTask -TaskName $name" in restore_script


def test_managed_launcher_consumes_one_shot_miner_start_suppression_policy(tmp_path):
    paths, _ = make_paths(tmp_path)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.config.write_text(
        "version: '1.0'\nprocesses:\n  krig_miner:\n    backend: fake\n"
        "    arguments: ['--user', 'wallet/worker']\npolicies: []\n",
        encoding="utf-8",
    )

    from resource_coordinator.installation import render_launcher
    script = render_launcher(paths)

    assert "--start-process" in script
    assert "--stop-process-on-shutdown" in script
    assert "upgrade-start-policy.json" in script
    assert "if (-not [bool]$policy.start_miner)" in script
    assert "if ($serveArgs[$i] -eq '--start-process') { $i++; continue }" in script


def test_setup_preserves_existing_configuration_and_is_idempotent(tmp_path, monkeypatch):
    paths, template = make_paths(tmp_path)
    paths.root.mkdir(parents=True)
    original = b"version: '1.0'\nprocesses: {}\npolicies: []\n# user comment\n"
    paths.config.write_bytes(original)
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(paths.token))
    monkeypatch.setattr("resource_coordinator.installation.load_or_create_token", lambda: "not printed")
    monkeypatch.setattr("resource_coordinator.installation.credential_doctor", _secure_credential_report)
    tasks = MemoryTasks()
    manager = ManagedInstallation(paths, tasks, template=template)
    manager._service_status = lambda: None
    manager._wait_for_service = lambda timeout=30.0: {"service_state": "ready"}

    first = manager.setup(apply=True, mode="logon")
    second = manager.setup(apply=True, mode="logon")

    assert first["status"] == "degraded"
    assert first["mining_warning"] is not None
    assert paths.config.read_bytes() == original
    assert paths.state.exists() is False
    assert paths.launcher.read_text(encoding="utf-8").startswith(f"# {TASK_MARKER}")
    assert len(tasks.install_calls) == 2
    assert tasks.items["ResourceCoordinator-KRig-Logon"].enabled is True
    assert second["created"] == []


def test_setup_copies_template_only_when_configuration_is_missing(tmp_path, monkeypatch):
    paths, template = make_paths(tmp_path)
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(paths.token))
    monkeypatch.setattr("resource_coordinator.installation.load_or_create_token", lambda: "not printed")
    monkeypatch.setattr("resource_coordinator.installation.credential_doctor", _secure_credential_report)
    manager = ManagedInstallation(paths, MemoryTasks(), template=template)
    manager._service_status = lambda: None
    manager._wait_for_service = lambda timeout=30.0: {"service_state": "ready"}

    result = manager.setup(apply=True)

    assert paths.config.read_bytes() == template.read_bytes()
    assert result["status"] == "degraded"
    assert "No miner process" in result["mining_warning"]


def test_setup_marks_valid_miner_identity_as_applied(tmp_path, monkeypatch):
    paths, template = make_paths(tmp_path)
    paths.root.mkdir(parents=True)
    paths.config.write_text(
        "version: '1.0'\nprocesses:\n  krig_miner:\n    backend: fake\n"
        "    arguments: ['--user', 'wallet/worker']\npolicies: []\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(paths.token))
    monkeypatch.setattr("resource_coordinator.installation.load_or_create_token", lambda: "not printed")
    monkeypatch.setattr("resource_coordinator.installation.credential_doctor", _secure_credential_report)
    manager = ManagedInstallation(paths, MemoryTasks(), template=template)
    manager._service_status = lambda: None
    manager._wait_for_service = lambda timeout=30.0: {"service_state": "ready"}

    result = manager.setup(apply=True)

    assert result["status"] == "applied"
    assert result["miner_identity_configured"] is True
    assert result["mining_warning"] is None


def test_setup_installs_optional_read_only_viewer_without_starting_miner(tmp_path, monkeypatch):
    paths, template = make_paths(tmp_path)
    paths.root.mkdir(parents=True)
    log_path = paths.root / "captured-miner-output.log"
    paths.config.write_text(
        "version: '1.0'\nprocesses:\n  krig_miner:\n    backend: fake\n"
        f"    arguments: ['--user', 'wallet/worker']\n    stdout_log_path: '{log_path}'\npolicies: []\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(paths.token))
    monkeypatch.setattr("resource_coordinator.installation.load_or_create_token", lambda: "not printed")
    monkeypatch.setattr("resource_coordinator.installation.credential_doctor", _secure_credential_report)
    tasks = MemoryTasks()
    manager = ManagedInstallation(paths, tasks, template=template)
    manager._service_status = lambda: pytest.fail("startup install must not query or launch service")

    result = manager.setup(apply=True, activate=False, viewer=True)

    viewer = tasks.items["KRig-Live-Output-Viewer"]
    assert result["viewer_task"]["name"] == viewer.name
    assert viewer.enabled is True and viewer.mode == "viewer"
    viewer_script = paths.viewer.read_text(encoding="utf-8")
    assert viewer_script.startswith(f"# {TASK_MARKER}")
    assert str(log_path) in viewer_script
    assert "miner/pause" not in viewer_script


def test_setup_refuses_to_overwrite_unmarked_managed_launcher(tmp_path, monkeypatch):
    paths, template = make_paths(tmp_path)
    paths.root.mkdir(parents=True)
    paths.config.write_text("version: '1.0'\nprocesses: {}\npolicies: []\n", encoding="utf-8")
    paths.launcher.write_text("# user-owned launcher\n", encoding="utf-8")
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(paths.token))
    monkeypatch.setattr("resource_coordinator.installation.load_or_create_token", lambda: "not printed")
    monkeypatch.setattr("resource_coordinator.installation.credential_doctor", _secure_credential_report)

    with pytest.raises(InstallationError, match="Refusing to overwrite"):
        manager = ManagedInstallation(paths, MemoryTasks(), template=template)
        manager._service_status = lambda: None
        manager._wait_for_service = lambda timeout=30.0: {"service_state": "ready"}
        manager.setup(apply=True)

    assert paths.launcher.read_text(encoding="utf-8") == "# user-owned launcher\n"


def test_setup_refuses_insecure_credential_before_installing_task(tmp_path, monkeypatch):
    paths, template = make_paths(tmp_path)
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(paths.token))
    monkeypatch.setattr("resource_coordinator.installation.load_or_create_token", lambda: "not printed")
    monkeypatch.setattr(
        "resource_coordinator.installation.credential_doctor",
        lambda: {**_secure_credential_report(), "acl_restricted": False},
    )
    tasks = MemoryTasks()
    manager = ManagedInstallation(paths, tasks, template=template)

    with pytest.raises(InstallationError, match="interactive user and SYSTEM"):
        manager.setup(apply=True)

    assert tasks.install_calls == []


def test_setup_failure_reports_completed_resources_without_exposing_credentials(tmp_path, monkeypatch):
    paths, template = make_paths(tmp_path)
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(paths.token))
    monkeypatch.setattr("resource_coordinator.installation.load_or_create_token", lambda: "secret-that-must-not-print")
    monkeypatch.setattr("resource_coordinator.installation.credential_doctor", _secure_credential_report)

    class FailingTasks(MemoryTasks):
        def install(self, mode, launcher, *, non_interactive=False):
            raise RuntimeError("task registration denied")

    manager = ManagedInstallation(paths, FailingTasks(), template=template)

    with pytest.raises(InstallationError) as error:
        manager.setup(apply=True)

    message = str(error.value)
    assert "installing and enabling the startup task" in message
    assert "configuration, operator credential, launcher" in message
    assert "task registration denied" in message
    assert "secret-that-must-not-print" not in message


def test_startup_status_names_only_enabled_owned_task_as_authoritative(tmp_path):
    paths, _ = make_paths(tmp_path)
    tasks = MemoryTasks()
    logon = tasks.install("logon", paths.launcher)
    tasks.set_enabled(logon, True)
    tasks.items["foreign"] = StartupTask("foreign", "logon", True, "Running", "mcarls", "Highest", "other.ps1", False)

    report = ManagedInstallation(paths, tasks).startup_status()

    assert report["authoritative"] == "ResourceCoordinator-KRig-Logon"
    assert [item["name"] for item in report["tasks"]] == ["ResourceCoordinator-KRig-Logon", "foreign"]


def test_startup_disable_is_idempotent_and_does_not_stop_running_service(tmp_path):
    paths, _ = make_paths(tmp_path)
    tasks = MemoryTasks()
    task = tasks.install("logon", paths.launcher)
    tasks.set_enabled(task, True)
    manager = ManagedInstallation(paths, tasks)
    manager._service_status = lambda: {"service_state": "ready"}

    report = manager.startup("disable", apply=True)

    assert report["status"] == "applied"
    assert tasks.items[task.name].enabled is False
    assert manager._service_status()["service_state"] == "ready"


def test_startup_install_registers_task_without_starting_service(tmp_path, monkeypatch):
    paths, template = make_paths(tmp_path)
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(paths.token))
    monkeypatch.setattr("resource_coordinator.installation.load_or_create_token", lambda: "not printed")
    monkeypatch.setattr("resource_coordinator.installation.credential_doctor", _secure_credential_report)
    tasks = MemoryTasks()
    manager = ManagedInstallation(paths, tasks, template=template)
    manager._service_status = lambda: pytest.fail("startup install must not query or launch service")

    result = manager.startup("install", apply=True, mode="logon")

    assert result["status"] == "degraded"
    assert result["service_activation"] == "not-started-by-startup-command"
    assert tasks.start_calls == []


@pytest.mark.parametrize(
    "status, message",
    [
        (None, "configuration cannot identify a durable journal"),
        ({"service_state": "draining", "gpu_inference": {}}, "not ready"),
        ({"service_state": "ready", "gpu_inference": {"is_restart_inhibited": True}}, "restart-inhibited"),
    ],
)
def test_teardown_refuses_unknown_or_active_service_state_without_changing_tasks(tmp_path, status, message):
    paths, _ = make_paths(tmp_path)
    tasks = MemoryTasks()
    task = tasks.install("logon", paths.launcher)
    tasks.set_enabled(task, True)
    manager = ManagedInstallation(paths, tasks)
    manager._service_status = lambda: status

    with pytest.raises(InstallationError, match=message):
        manager.teardown(apply=True)

    assert task.name in tasks.items
    assert tasks.items[task.name].enabled is True


def test_teardown_asks_coordinator_to_drain_active_inference_before_removing_startup(tmp_path, monkeypatch):
    import httpx

    paths, _ = make_paths(tmp_path)
    _write_offline_journal(paths)
    tasks = MemoryTasks()
    task = tasks.install("logon", paths.launcher)
    tasks.set_enabled(task, True)
    manager = ManagedInstallation(paths, tasks)
    manager._service_status = lambda: {
        "service_state": "ready",
        "gpu_inference": {"active_count": 1, "pending_count": 2, "is_restart_inhibited": False},
        "processes": {},
    }
    manager._coordinator_port_open = lambda: False
    shutdown_requests = []
    manager._request_graceful_shutdown = lambda token: shutdown_requests.append(token) or httpx.Response(202)
    monkeypatch.setattr("resource_coordinator.installation.load_token", lambda: "unit-test-token")

    result = manager.teardown(apply=True)

    assert result["status"] == "applied"
    assert shutdown_requests == ["unit-test-token"]
    assert task.name not in tasks.items


def test_teardown_requires_valid_durable_journal_before_requesting_shutdown(tmp_path):
    paths, _ = make_paths(tmp_path)
    manager = ManagedInstallation(paths, MemoryTasks())
    manager._service_status = lambda: {
        "service_state": "ready",
        "gpu_inference": {"active_count": 0, "pending_count": 0, "is_restart_inhibited": False},
        "processes": {},
    }
    manager._request_graceful_shutdown = lambda token: pytest.fail("must preserve running service")

    with pytest.raises(InstallationError, match="valid durable journal"):
        manager.teardown(apply=True)


def test_offline_teardown_removes_owned_startup_artifacts_and_preserves_durable_data(tmp_path):
    paths, _ = make_paths(tmp_path)
    state_path = _write_offline_journal(paths)
    paths.launcher.write_text(f"# {TASK_MARKER}\n", encoding="utf-8")
    paths.viewer.write_text(f"# {TASK_MARKER}\n", encoding="utf-8")
    paths.logs.mkdir(parents=True)
    log = paths.logs / "miner.log"
    log.write_text("preserved", encoding="utf-8")
    tasks = MemoryTasks()
    task = tasks.install("logon", paths.launcher)
    tasks.set_enabled(task, True)
    manager = ManagedInstallation(paths, tasks)
    manager._service_status = lambda: None

    result = manager.teardown(apply=True)

    assert result["offline_recovery"] is True
    assert result["tasks_uninstalled"] == [task.name]
    assert not paths.launcher.exists() and not paths.viewer.exists()
    assert state_path.is_file() and paths.config.is_file() and log.read_text(encoding="utf-8") == "preserved"


def test_offline_teardown_refuses_uncertain_inference_journal(tmp_path):
    paths, _ = make_paths(tmp_path)
    _write_offline_journal(paths, requests="request-1:possibly_forwarded")
    tasks = MemoryTasks()
    task = tasks.install("logon", paths.launcher)
    tasks.set_enabled(task, True)
    manager = ManagedInstallation(paths, tasks)
    manager._service_status = lambda: None

    with pytest.raises(InstallationError, match="unresolved inference"):
        manager.teardown(apply=True)

    assert task.name in tasks.items


def test_offline_teardown_never_terminates_a_verified_running_owned_miner(tmp_path, monkeypatch):
    import psutil

    from resource_coordinator.core.durable_state import PersistedProcess, StateCodec

    paths, _ = make_paths(tmp_path)
    state_path = _write_offline_journal(paths)
    state = StateCodec.load(state_path)
    state.processes["krig_miner"] = PersistedProcess(
        name="krig_miner", pid=24680, create_time=1234.5, lifecycle_owner="coordinator"
    )
    StateCodec.save_atomic(state, state_path)

    class LiveProcess:
        def create_time(self):
            return 1234.5

    monkeypatch.setattr(psutil, "Process", lambda pid: LiveProcess())
    tasks = MemoryTasks()
    task = tasks.install("logon", paths.launcher)
    tasks.set_enabled(task, True)
    manager = ManagedInstallation(paths, tasks)
    manager._service_status = lambda: None
    manager._wait_for_service = lambda timeout=30.0: None

    with pytest.raises(InstallationError, match=r"verified PID\(s\): \[24680\]"):
        manager.teardown(apply=True)

    assert task.name in tasks.items
    assert tasks.start_calls == []


def test_teardown_plan_preserves_configuration_credentials_journal_and_logs(tmp_path):
    paths, _ = make_paths(tmp_path)
    manager = ManagedInstallation(paths, MemoryTasks())

    plan = manager.plan_teardown()

    assert plan["status"] == "planned"
    assert set(plan["preserved"]) == {str(paths.config), str(paths.token), str(paths.state), str(paths.logs)}
    assert set(plan["targets"]) == {str(paths.launcher), "RC-owned startup tasks"}


def test_health_status_is_degraded_for_limit_mismatch_not_healthy_for_http_200():
    from resource_coordinator.installation import classify_doctor

    report = classify_doctor(
        {
            "service_ready": True,
            "task_ready": True,
            "credential_ready": True,
            "configured_power_limit_w": 550,
            "effective_power_limit_w": 600,
            "configured_gpu_settings": {"memory_clock_mhz": 7001},
            "gpu": {"memory_clock_mhz": 5000},
            "miner_owned": True,
        }
    )

    assert report["status"] == "degraded"
    assert "effective GPU power limit 600 W does not match configured 550 W" in report["warnings"]
    assert any("observed GPU memory clock 5000 MHz" in item for item in report["warnings"])


def test_doctor_reports_requested_gpu_flags_without_claiming_dynamic_clock_is_effective():
    from resource_coordinator.config import CoordinatorConfig, ProcessConfig
    from resource_coordinator.installation import _configured_gpu_settings

    config = CoordinatorConfig(
        processes={
            "krig_miner": ProcessConfig(
                name="krig_miner",
                arguments=[
                    "--gpu-plimit", "550", "--gpu-cclock", "2400",
                    "--gpu-coffset", "225", "--gpu-mclock", "7001",
                ],
                backend="fake",
            )
        }
    )

    assert _configured_gpu_settings(config) == {
        "power_limit_w": 550.0,
        "core_clock_mhz": 2400.0,
        "core_offset_mhz": 225.0,
        "memory_clock_mhz": 7001.0,
    }


def test_health_status_reports_unavailable_task_inventory_as_degraded():
    from resource_coordinator.installation import classify_doctor

    report = classify_doctor(
        {
            "service_ready": True,
            "credential_ready": True,
            "task_ready": False,
            "task_inventory_error": "CIM access denied",
        }
    )

    assert report["status"] == "degraded"
    assert any("CIM access denied" in warning for warning in report["warnings"])


def test_startup_task_health_requires_the_expected_service_identity(monkeypatch):
    from resource_coordinator.installation import _task_identity_valid

    monkeypatch.setattr("resource_coordinator.installation.getpass.getuser", lambda: "mcarls")

    assert _task_identity_valid({"mode": "boot", "user_id": "S-1-5-18"})
    assert _task_identity_valid({"mode": "logon", "user_id": "XERES\\mcarls"})
    assert not _task_identity_valid({"mode": "logon", "user_id": "other-user"})


def test_doctor_resolves_implicit_capture_path_to_managed_log_directory(tmp_path):
    from resource_coordinator.installation import _effective_log_path

    process = type("Process", (), {"stdout_log_path": None})()

    assert _effective_log_path("krig_miner", process, tmp_path / "logs") == tmp_path / "logs" / "krig_miner.log"


def test_doctor_preserves_explicit_capture_path(tmp_path):
    from resource_coordinator.installation import _effective_log_path

    explicit = tmp_path / "custom" / "miner-output.txt"
    process = type("Process", (), {"stdout_log_path": str(explicit)})()

    assert _effective_log_path("krig_miner", process, tmp_path / "logs") == explicit


def test_doctor_degrades_when_configured_log_directory_is_not_writable():
    from resource_coordinator.installation import classify_doctor

    report = classify_doctor({
        "service_ready": True,
        "credential_ready": True,
        "task_ready": True,
        "log_paths": {"krig_miner": {"parent_writable": False}},
    })

    assert report["status"] == "degraded"
    assert any("capture path" in warning for warning in report["warnings"])


def test_doctor_compares_running_source_to_expected_package_path(tmp_path):
    from resource_coordinator.installation import _runtime_source_matches

    expected = tmp_path / "resource_coordinator" / "__init__.py"
    expected.parent.mkdir()
    expected.write_text("", encoding="utf-8")

    assert _runtime_source_matches(str(expected), expected)
    assert not _runtime_source_matches(str(tmp_path / "old-checkout" / "__init__.py"), expected)
    assert not _runtime_source_matches(None, expected)


def test_doctor_degrades_for_stale_running_coordinator_source_or_version():
    from resource_coordinator.installation import classify_doctor

    report = classify_doctor({
        "service_ready": True,
        "credential_ready": True,
        "task_ready": True,
        "runtime_source_matches": False,
        "runtime_version_matches": False,
    })

    assert report["status"] == "degraded"
    assert any("source/version" in warning for warning in report["warnings"])


def test_doctor_does_not_claim_unobservable_core_policy_is_verified():
    from resource_coordinator.installation import classify_doctor

    report = classify_doctor({
        "service_ready": True,
        "runtime_source_matches": True,
        "runtime_version_matches": True,
        "credential_ready": True,
        "task_ready": True,
        "configured_gpu_settings": {"core_clock_mhz": 2400, "core_offset_mhz": 225},
        "gpu_policy_verification": {"core_clock_mhz": "observed_dynamic_only", "core_offset_mhz": "unavailable"},
    })

    assert report["status"] == "degraded"
    assert any("core clock lock" in warning for warning in report["warnings"])
    assert any("core offset" in warning for warning in report["warnings"])


@pytest.mark.parametrize("gaming_state", ["stopping", "active", "restoring", "failed"])
def test_gpu_idle_condition_cannot_resume_mining_during_gaming_or_reconciliation(gaming_state):
    from resource_coordinator.core.service import _gpu_idle_sampling_allowed

    condition = {"threshold_pct": 20, "window_seconds": 60, "samples": []}

    assert _gpu_idle_sampling_allowed(condition, {"state": "inactive"}, manual_override=True)
    assert not _gpu_idle_sampling_allowed(condition, {"state": gaming_state}, manual_override=True)
    assert not _gpu_idle_sampling_allowed(condition, {"state": "inactive"}, manual_override=False)


@pytest.mark.parametrize(
    "action,is_gpu_pause,should_clear",
    [("pause", False, True), ("stop", False, True), ("pause", True, False), ("resume", False, False)],
)
def test_manual_pause_or_stop_replaces_stale_gpu_idle_condition(action, is_gpu_pause, should_clear):
    from resource_coordinator.core.service import _manual_action_clears_gpu_idle_condition

    assert _manual_action_clears_gpu_idle_condition(action, gpu_idle_pause=is_gpu_pause) is should_clear


@pytest.mark.parametrize("gaming_state", ["stopping", "active", "restoring", "failed"])
def test_manual_miner_mutations_are_blocked_during_gaming_hold(gaming_state):
    from resource_coordinator.core.service import _manual_miner_mutations_allowed

    allowed = _manual_miner_mutations_allowed({"state": gaming_state})

    assert not allowed


def test_manual_miner_mutations_are_available_outside_gaming():
    from resource_coordinator.core.service import _manual_miner_mutations_allowed

    assert _manual_miner_mutations_allowed({"state": "inactive"})
