from __future__ import annotations

import pytest
from pathlib import Path
import tempfile

from resource_coordinator import installation


class _Credentials:
    def ensure(self, token_path):
        self.token_path = token_path

    def doctor(self, token_path):
        self.token_path = token_path
        return {"credential_file_exists": True, "credential_file_readable": True,
                "credential_valid": True, "acl_restricted": True,
                "environment_override_matches_file": True}

    def load(self, token_path):
        self.token_path = token_path
        return "test-only-token"


class _Tasks:
    def status(self):
        return []


def _runtime(tmp_path, **overrides):
    options = {
        "task_names": {
            "boot": "ResourceCoordinator-H4-run-boot",
            "logon": "ResourceCoordinator-H4-run-logon",
            "viewer": "ResourceCoordinator-H4-run-viewer",
        },
        "coordinator_url": "http://127.0.0.1:45431",
        "listen_port": 45431,
        "guest_mutation_guard": lambda: None,
        "credential_provider": _Credentials(),
    }
    options.update(overrides)
    return installation.InstallationRuntime(**options)


def test_nonproduction_installation_identities_require_a_guest_guard():
    runtime_type = getattr(installation, "InstallationRuntime", None)
    assert runtime_type is not None, "the installer needs an explicit runtime-injection boundary"

    custom_tasks = {
        "boot": "ResourceCoordinator-H4-run-boot",
        "logon": "ResourceCoordinator-H4-run-logon",
        "viewer": "ResourceCoordinator-H4-run-viewer",
    }
    with pytest.raises(installation.InstallationError, match="guest mutation guard"):
        runtime_type(task_names=custom_tasks, coordinator_url="http://127.0.0.1:45431", listen_port=45431)


def test_windows_task_backend_refuses_custom_task_names_without_guard():
    custom_tasks = {
        "boot": "ResourceCoordinator-H4-run-boot",
        "logon": "ResourceCoordinator-H4-run-logon",
        "viewer": "ResourceCoordinator-H4-run-viewer",
    }
    with pytest.raises(installation.InstallationError, match="guest mutation guard"):
        installation.WindowsStartupTaskBackend(task_names=custom_tasks)


def test_windows_task_backend_requires_explicit_test_helper_root(tmp_path):
    custom_tasks = {
        "boot": "ResourceCoordinator-H4-run-boot",
        "logon": "ResourceCoordinator-H4-run-logon",
        "viewer": "ResourceCoordinator-H4-run-viewer",
    }
    with pytest.raises(installation.InstallationError, match="explicit test-owned helper directory"):
        installation.WindowsStartupTaskBackend(task_names=custom_tasks,
                                               guest_mutation_guard=lambda: None)


def test_task_helper_uses_payload_task_identities_instead_of_production_literals():
    script = installation._TASKS_POWERSHELL
    assert "$payload.task_names" in script
    assert "ResourceCoordinator-KRig-Boot" not in script
    assert "ResourceCoordinator-KRig-UserLogon" not in script
    assert "KRig-Live-Output-Viewer" not in script


def test_legacy_attribution_accepts_only_runtime_bound_coordinator_task_names():
    custom = {
        "boot": "ResourceCoordinator-H4-run-boot",
        "logon": "ResourceCoordinator-H4-run-logon",
        "viewer": "ResourceCoordinator-H4-run-viewer",
    }
    assert installation._is_coordinator_task_name(custom["logon"], custom)
    assert installation._is_coordinator_task_name(custom["boot"], custom)
    assert not installation._is_coordinator_task_name(custom["viewer"], custom)
    assert not installation._is_coordinator_task_name("ResourceCoordinator-KRig-UserLogon", custom)
    assert installation._is_coordinator_task_name("ResourceCoordinator-KRig-UserLogon", installation.TASK_NAMES)


def test_nonproduction_runtime_requires_scoped_credentials_and_nonproduction_port():
    with pytest.raises(installation.InstallationError, match="credential provider"):
        _runtime(Path("unused"), credential_provider=None)
    with pytest.raises(installation.InstallationError, match="production Coordinator port"):
        _runtime(Path("unused"), coordinator_url=installation.COORDINATOR_URL,
                 listen_port=1235)


def test_isolated_paths_keep_every_mutable_artifact_below_test_root(tmp_path):
    paths = installation.InstallationPaths.isolated(
        root=tmp_path / "h4-rc-run", repository=Path(__file__).resolve().parents[1],
        python=Path("C:/Python/python.exe"),
    )
    root = paths.root
    for path in (paths.config, paths.state, paths.token, paths.logs, paths.launcher,
                 paths.viewer, paths.coordinator_log, paths.upgrade_receipt, paths.upgrade_policy):
        assert path == root or root in path.parents


def test_managed_installation_rejects_test_root_inside_source_tree():
    source = Path(__file__).resolve().parents[1]
    paths = installation.InstallationPaths.isolated(
        root=source / "h4-test-root-must-not-exist", repository=source,
        python=Path("C:/Python/python.exe"),
    )
    with pytest.raises(installation.InstallationError, match="overlaps the source checkout"):
        installation.ManagedInstallation(paths, _Tasks(), runtime=_runtime(Path("unused")))


def test_runtime_observers_are_bound_to_the_isolated_listener_and_process():
    calls = []
    runtime = _runtime(
        Path("unused"),
        listener_observer=lambda port, host: calls.append((port, host)) or {"verified": False},
        process_is_alive=lambda pid, created: calls.append((pid, created)) or None,
    )
    assert runtime.listener_details() == {"verified": False}
    assert runtime.process_alive(71, 12.5) is None
    assert calls == [(45431, "127.0.0.1"), (71, 12.5)]


def test_managed_installation_rejects_helper_root_outside_guest_test_root():
    source = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="h4-install-root-") as temporary:
        tmp_path = Path(temporary)
        root = tmp_path / "h4-rc-run"
        paths = installation.InstallationPaths.isolated(root=root, repository=source,
                                                         python=Path("C:/Python/python.exe"))
        runtime = _runtime(tmp_path)
        backend = installation.WindowsStartupTaskBackend(
            task_names=runtime.task_names, managed_root=tmp_path / "outside-helper",
            guest_mutation_guard=runtime.guest_mutation_guard,
        )
        with pytest.raises(installation.InstallationError, match="helper directory escapes"):
            installation.ManagedInstallation(paths, backend, runtime=runtime)


def test_production_cli_exposes_no_guest_runtime_overrides():
    from resource_coordinator import cli_parser

    for argv in (["system", "setup"], ["system", "upgrade"], ["system", "teardown"], ["system", "repair"], ["doctor"]):
        parsed = cli_parser.parse_args(argv)
        assert not hasattr(parsed, "task_names")
        assert not hasattr(parsed, "listen_port")
        assert not hasattr(parsed, "guest_mutation_guard")
        assert not hasattr(parsed, "isolated")
    with pytest.raises(SystemExit):
        cli_parser.parse_args(["system", "setup", "--listen-port", "45431"])
