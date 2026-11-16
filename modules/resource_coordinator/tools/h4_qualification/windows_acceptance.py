#!/usr/bin/env python3
"""Fail-closed launcher for isolated Windows H4 checks.

Default operation is a read-only preflight plus artifact initialization.
Mutating task and installation lifecycle profiles require independently
observed guest identity, complete inventories, scoped resources, and explicit
operator authorization. No profile falls back to the source host defaults.
"""

import argparse
from dataclasses import asdict
import json
import os
import secrets
import socket
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

try:
    from tools.h4_qualification.python_compat import (
        PythonCompatibilityError,
        enforce_cli_python,
        require_supported_python,
    )
except ImportError:  # pragma: no cover - direct harness execution fallback
    _compat_dir = str(Path(__file__).resolve().parent)
    if _compat_dir not in sys.path:
        sys.path.insert(0, _compat_dir)
    from python_compat import (  # type: ignore[no-redef]
        PythonCompatibilityError,
        enforce_cli_python,
        require_supported_python,
    )

if __name__ == "__main__":
    enforce_cli_python("windows_acceptance", sys.argv[1:])
require_supported_python("windows_acceptance")

try:
    from tools.h4_qualification.source_integrity import (
        HASH_ALGORITHM,
        SourceIntegrityError,
        load_source_manifest,
        manifest_entry_for_role,
        verify_source_tree,
    )
except ImportError:  # pragma: no cover - direct harness execution fallback
    from source_integrity import (  # type: ignore[no-redef]
        HASH_ALGORITHM,
        SourceIntegrityError,
        load_source_manifest,
        manifest_entry_for_role,
        verify_source_tree,
    )


AUTHORIZATION_PHRASE = "I AUTHORIZE DISPOSABLE H4 WINDOWS MUTATION"
FAULT_STAGES = (
    "after_prepared_receipt", "after_old_service_stopped", "before_task_replacement",
    "after_task_replacement", "after_new_service_ready",
)
GUEST_MARKERS = (
    ("microsoft corporation", "virtual machine"),
    ("microsoft", "virtual machine"),
    ("vmware",),
    ("innotek",),
    ("virtualbox",),
    ("qemu",),
    ("xen",),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_powershell(*, test_root: Optional[Path] = None,
                    listener_port: Optional[int] = None) -> Dict[str, Any]:
    shell = next((candidate for candidate in ("pwsh.exe", "powershell.exe")
                  if _which(candidate)), None)
    if shell is None:
        raise RuntimeError("PowerShell is unavailable")
    script = r"""
$ErrorActionPreference = 'Stop'
$result = [ordered]@{schema_version=1; queries=[ordered]@{}}
$testRoot = [string]$env:RC_H4_TEST_ROOT
$testRootPrefix = if ($testRoot) { [IO.Path]::GetFullPath($testRoot).TrimEnd('\') + '\' } else { '' }
try {
  $cs = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
  $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
  $result.computer = @{manufacturer=[string]$cs.Manufacturer; model=[string]$cs.Model; hypervisor_present=[bool]$cs.HypervisorPresent}
  $result.os = @{caption=[string]$os.Caption; version=[string]$os.Version; build=[string]$os.BuildNumber}
  $result.queries.system = 'available'
} catch { $result.queries.system = 'error'; $result.errors = @("system_query:$($_.Exception.GetType().Name)") }
try {
  $tasks = @(Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.TaskName -match 'ResourceCoordinator|KRig-Live-Output-Viewer|^RC-Disposable-' } | ForEach-Object {
    $actionText = (@($_.Actions | ForEach-Object { [string]$_.Execute + ' ' + [string]$_.Arguments }) -join ';')
    @{name=[string]$_.TaskName; state=[string]$_.State; test_root_action=[bool]($testRootPrefix -and $actionText.IndexOf($testRootPrefix,[StringComparison]::OrdinalIgnoreCase) -ge 0)}
  })
  $result.rc_tasks = $tasks
  $result.queries.tasks = 'available'
} catch { $result.queries.tasks = 'error'; $result.errors += "task_query:$($_.Exception.GetType().Name)" }
try {
  $services = @(Get-CimInstance Win32_Service -ErrorAction Stop | Where-Object { $_.Name -match 'Resource.?Coordinator|GPUCoordinator' } | ForEach-Object { @{name=[string]$_.Name; state=[string]$_.State} })
  $result.rc_services = $services
  $result.queries.services = 'available'
} catch { $result.queries.services = 'error'; $result.errors += "service_query:$($_.Exception.GetType().Name)" }
try {
  $matches = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $_.Name -match 'resource-coordinator|gpu-coordinator|krig-miner|srbminer' -or
    ($_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'resource_coordinator\.cli')
  } | ForEach-Object {
    $created = if ($_.CreationDate) { [Management.ManagementDateTimeConverter]::ToDateTime([string]$_.CreationDate).ToUniversalTime().ToFileTimeUtc() / 10000000 - 11644473600 } else { 0 }
    @{name=[string]$_.Name; pid=[int]$_.ProcessId; creation_time=[double]$created; executable_path=[string]$_.ExecutablePath}
  })
  $result.rc_processes = $matches
  $result.queries.processes = 'available'
} catch { $result.queries.processes = 'error'; $result.errors += "process_query:$($_.Exception.GetType().Name)" }
$result | ConvertTo-Json -Depth 6 -Compress
"""
    env = os.environ.copy()
    if test_root is not None:
        env["RC_H4_TEST_ROOT"] = str(test_root.resolve())
    if listener_port is not None:
        if type(listener_port) is not int or not 1024 <= listener_port <= 65535 or listener_port == 1235:
            raise RuntimeError("H4 listener inventory port is invalid")
        env["RC_H4_LISTENER_PORT"] = str(listener_port)
        script = script.replace(
            "$result | ConvertTo-Json -Depth 6 -Compress",
            r"""
try {
  $port=[int]$env:RC_H4_LISTENER_PORT
  $listeners=@(Get-CimInstance -Namespace root/StandardCimv2 -ClassName MSFT_NetTCPConnection -Filter ("State = 2 AND LocalPort = " + $port) -ErrorAction Stop | ForEach-Object {
    $owner=Get-CimInstance Win32_Process -Filter ("ProcessId=" + [int]$_.OwningProcess) -ErrorAction Stop
    $created=if ($owner.CreationDate) { [Management.ManagementDateTimeConverter]::ToDateTime([string]$owner.CreationDate).ToUniversalTime().ToFileTimeUtc() / 10000000 - 11644473600 } else { 0 }
    @{port=$port;local_address=[string]$_.LocalAddress;pid=[int]$_.OwningProcess;creation_time=[double]$created;executable_path=[string]$owner.ExecutablePath}
  })
  $result.listener_port=$port; $result.listener_rows=$listeners; $result.queries.listener='available'
} catch { $result.queries.listener='error'; $result.errors += "listener_query:$($_.Exception.GetType().Name)" }
$result | ConvertTo-Json -Depth 6 -Compress
""",
        )
    completed = subprocess.run(
        [shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=20, check=False, env=env,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"PowerShell preflight exited {completed.returncode}")
    value = json.loads(completed.stdout.strip().splitlines()[-1])
    if not isinstance(value, dict):
        raise RuntimeError("PowerShell preflight returned malformed JSON")
    return value


def _which(name: str) -> Optional[str]:
    import shutil
    return shutil.which(name)


def _is_reparse_point(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        if os.name == "nt":
            attributes = getattr(path.lstat(), "st_file_attributes", 0)
            return bool(attributes & 0x400)
    except OSError:
        return True
    return False


def guest_identity(evidence: Dict[str, Any]) -> bool:
    """Require WMI system identity consistent with a virtual guest, not a CLI flag."""
    computer = evidence.get("computer")
    if not isinstance(computer, dict) or evidence.get("queries", {}).get("system") != "available":
        return False
    manufacturer = str(computer.get("manufacturer", "")).casefold()
    model = str(computer.get("model", "")).casefold()
    combined = f"{manufacturer} {model}"
    return bool(computer.get("hypervisor_present") and any(
        all(marker in combined for marker in marker_set) for marker_set in GUEST_MARKERS
    ))


def guard_reasons(evidence: Dict[str, Any], test_root: Path, *, is_windows: bool,
                  owned_task_names: Sequence[str] = (),
                  owned_processes: Sequence[Dict[str, Any]] = ()) -> list:
    reasons = []
    if not is_windows:
        reasons.append("not_windows")
    if not guest_identity(evidence):
        reasons.append("guest_identity_not_independently_verified")
    queries = evidence.get("queries", {})
    for key in ("tasks", "services", "processes"):
        if queries.get(key) != "available":
            reasons.append(f"{key}_inventory_unavailable")
    owned_names = set(owned_task_names)
    tasks = evidence.get("rc_tasks") or []
    unexpected_tasks = [task for task in tasks if not (
        isinstance(task, dict) and task.get("name") in owned_names and task.get("test_root_action") is True
    )]
    if unexpected_tasks:
        reasons.append("rc_task_present")
    if evidence.get("rc_services"):
        reasons.append("rc_service_present")
    processes = evidence.get("rc_processes") or []
    unexpected_processes = [process for process in processes if not (
        isinstance(process, dict) and
        any(
            type(process.get("pid")) is int and type(item.get("pid")) is int and
            process["pid"] == item["pid"] and
            isinstance(process.get("creation_time"), (int, float)) and
            isinstance(item.get("creation_time"), (int, float)) and
            abs(float(process["creation_time"]) - float(item["creation_time"])) <= 1.5 and
            str(process.get("executable_path", "")).casefold() ==
            str(item.get("executable_path", "")).casefold()
            for item in owned_processes if isinstance(item, dict)
        )
    )]
    if unexpected_processes:
        reasons.append("rc_or_miner_process_present")
    listener_port = evidence.get("listener_port")
    if listener_port is not None:
        if queries.get("listener") != "available":
            reasons.append("listener_inventory_unavailable")
        else:
            listener_rows = evidence.get("listener_rows") or []
            owned_listener = len(listener_rows) == 1 and any(
                isinstance(row, dict) and isinstance(owner, dict) and
                type(row.get("port")) is int and row.get("port") == listener_port and
                type(row.get("pid")) is int and row.get("pid") == owner.get("pid") and
                isinstance(row.get("creation_time"), (int, float)) and
                isinstance(owner.get("creation_time"), (int, float)) and
                abs(float(row["creation_time"]) - float(owner["creation_time"])) <= 1.5 and
                str(row.get("executable_path", "")).casefold() ==
                str(owner.get("executable_path", "")).casefold()
                for row in listener_rows for owner in owned_processes
            )
            if listener_rows and not owned_listener:
                reasons.append("listener_port_owner_unverified")
    if not test_root.is_absolute() or test_root.name.casefold().startswith("h4-rc-") is False:
        reasons.append("test_root_must_be_absolute_and_h4_scoped")
    if test_root.exists() and _is_reparse_point(test_root):
        reasons.append("test_root_is_reparse_or_symbolic_link")
    return reasons


def task_path_reasons(test_root: Path) -> list:
    """Validate a task-mutation root against source, junction, and artifact hazards."""
    reasons = []
    if not test_root.is_absolute() or not test_root.is_dir():
        reasons.append("task_test_root_must_be_existing_absolute_directory")
        return reasons
    path_chain = [test_root, *test_root.parents]
    if any(_is_reparse_point(path) for path in path_chain if path.exists()):
        reasons.append("test_root_path_contains_reparse_point")
    module_root = Path(__file__).resolve().parents[2]
    if test_root == module_root or module_root in test_root.parents:
        reasons.append("task_test_root_must_be_outside_source_tree")
    if test_root.anchor.startswith("\\\\"):
        reasons.append("task_test_root_must_be_local_not_unc")
    protected_roots = [Path.home() / ".resource_coordinator", Path(os.environ.get("ProgramData", "C:/ProgramData"))]
    if any(test_root == candidate.resolve() or candidate.resolve() in test_root.parents for candidate in protected_roots):
        reasons.append("test_root_overlaps_protected_installation_path")
    ALLOWED_TOP_LEVEL_ARTIFACTS = frozenset({
        ".h4-test-root.json", "environment.json", "preflight.json", "test-results.json",
        "process-identity.json", "rollback-result.json", "cleanup-result.json", "cleanup-manifest.json",
        "pytest-output.log", "upgrade-receipts", "task-snapshots",
        "runs", "junit.xml",
    })
    children = list(test_root.iterdir())
    if not (test_root / ".h4-test-root.json").exists() and children:
        reasons.append("unmarked_test_root_not_empty")
    if any(child.name not in ALLOWED_TOP_LEVEL_ARTIFACTS and not child.name.startswith(("pytest-temp-", "junit-"))
           for child in children):
        reasons.append("test_root_contains_unrecognized_artifacts")
    if any(_is_reparse_point(child) for child in children):
        reasons.append("test_root_contains_reparse_point_artifact")
    return reasons


class GuestLifecycleError(RuntimeError):
    """Sanitized lifecycle failure carrying bounded stage and guard diagnostics."""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "lifecycle",
        reason_code: str = "RuntimeError",
        guard_reasons: Sequence[str] = (),
    ):
        super().__init__(message)
        self.stage = stage
        self.reason_code = reason_code
        self.guard_reasons = tuple(str(r) for r in guard_reasons)


class GuestMutationGate:
    """Recheck guest identity and inventories before each actual installer mutation."""

    def __init__(self, test_root: Path, task_names: Sequence[str], *, listener_port: Optional[int] = None):
        self.test_root = test_root.resolve()
        self.task_names = tuple(task_names)
        self.listener_port = listener_port
        self.owned_processes: list = []

    def allow_process(self, *, pid: int, creation_time: float, executable_path: Path) -> None:
        item = {
            "pid": pid, "creation_time": creation_time,
            "executable_path": str(executable_path.resolve()).casefold(),
        }
        if not any(existing == item for existing in self.owned_processes):
            self.owned_processes.append(item)

    def __call__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("guest mutation requires Windows")
        if os.environ.get("RC_H4_DISPOSABLE_GUEST_AUTHORIZED") != AUTHORIZATION_PHRASE:
            raise RuntimeError("separate disposable guest authorization is missing")
        evidence = _run_powershell(test_root=self.test_root, listener_port=self.listener_port)
        if self.listener_port is not None:
            evidence["listener_port"] = self.listener_port
        reasons = guard_reasons(
            evidence, self.test_root, is_windows=True,
            owned_task_names=self.task_names, owned_processes=self.owned_processes,
        )
        reasons.extend(task_path_reasons(self.test_root))
        if reasons:
            unique = sorted(set(reasons))
            raise GuestLifecycleError(
                "guest mutation guard refused the operation: " + ",".join(unique),
                stage="guard",
                reason_code="guest_mutation_guard_refused",
                guard_reasons=unique,
            )


class GuestCredentialProvider:
    """Create one dummy token in the isolated guest root and verify its exact ACL."""

    def __init__(self, root: Path, *, user: Optional[str] = None):
        self.root = root.resolve()
        self.user = user or os.environ.get("USERDOMAIN", "") + "\\" + os.environ.get("USERNAME", "")
        self.token = None
        if not self.user.strip("\\"):
            raise RuntimeError("guest interactive user identity is unavailable")

    def _check_path(self, token_path: Path) -> Path:
        path = token_path.resolve(strict=False)
        if path.parent != self.root or _is_reparse_point(token_path) or not path.name.endswith(".token"):
            raise RuntimeError("dummy credential path is outside the isolated guest root")
        return path

    def ensure(self, token_path: Path) -> None:
        path = self._check_path(token_path)
        self.root.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if not self.doctor(path).get("acl_restricted"):
                raise RuntimeError("existing dummy credential ACL is not safe")
            self.token = self.load(path)
            return
        token = secrets.token_urlsafe(32)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(token + "\n")
        self.token = token
        command = ["icacls.exe", str(path), "/inheritance:r", "/grant:r",
                   f"{self.user}:(R)", "*S-1-5-18:(R)", "*S-1-5-32-544:(F)", "/C"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
        if result.returncode:
            raise RuntimeError("could not restrict the dummy credential ACL")
        if not self.doctor(path).get("acl_restricted"):
            raise RuntimeError("dummy credential ACL did not match the isolated policy")

    def doctor(self, token_path: Path) -> Dict[str, Any]:
        path = self._check_path(token_path)
        script = r"""
$ErrorActionPreference='Stop'
$userSid=([Security.Principal.NTAccount]::new($env:RC_H4_USER)).Translate([Security.Principal.SecurityIdentifier]).Value
$acl=Get-Acl -LiteralPath $env:RC_H4_TOKEN_PATH
$read=[int][Security.AccessControl.FileSystemRights]::Read
$full=[int][Security.AccessControl.FileSystemRights]::FullControl
$rows=@($acl.Access | ForEach-Object { $sid=$_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value; @{sid=$sid;type=[string]$_.AccessControlType;read_only=([int]$_.FileSystemRights -eq $read);full=([int]$_.FileSystemRights -eq $full);inherited=[bool]$_.IsInherited} })
ConvertTo-Json -Compress -InputObject @{user_sid=$userSid;rows=$rows}
"""
        env = os.environ.copy()
        env["RC_H4_TOKEN_PATH"] = str(path)
        env["RC_H4_USER"] = self.user
        shell = _which("pwsh.exe") or _which("powershell.exe")
        if not shell or not path.is_file():
            return {"credential_file_exists": path.is_file(), "credential_file_readable": False,
                    "credential_valid": False, "acl_restricted": False,
                    "environment_override_matches_file": False}
        try:
            result = subprocess.run([shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                                    env=env, capture_output=True, text=True, timeout=10, check=False)
            acl_value = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {}
            rows = acl_value.get("rows", [])
            user_sid = acl_value.get("user_sid")
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            rows = []
            user_sid = None
        expected = {"S-1-5-18", "S-1-5-32-544", user_sid}
        by_sid = {row.get("sid"): row for row in rows} if isinstance(rows, list) else {}
        acl_ok = bool(user_sid and set(by_sid) == expected and len(rows) == 3 and all(
            row.get("type") == "Allow" and not row.get("inherited") for row in rows
        ) and by_sid.get(user_sid, {}).get("read_only") is True and
            by_sid.get("S-1-5-18", {}).get("read_only") is True and
            by_sid.get("S-1-5-32-544", {}).get("full") is True)
        try:
            value = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            value = ""
        return {"credential_file_exists": path.is_file(), "credential_file_readable": bool(value),
                "credential_valid": bool(value), "acl_restricted": acl_ok,
                "environment_override_matches_file": True}

    def load(self, token_path: Path) -> str:
        path = self._check_path(token_path)
        value = path.read_text(encoding="utf-8").strip()
        if not value:
            raise RuntimeError("dummy credential file is empty")
        return value


def _write_json(path: Path, value: Dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_cleanup_manifests(root: Path) -> list:
    path = root / "cleanup-manifest.json"
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise RuntimeError("cleanup manifest schema is invalid")
    phases = value.get("phases")
    if not isinstance(phases, list):
        raise RuntimeError("cleanup manifest phases are invalid")
    return phases


def _manifest_task_names(root: Path) -> list:
    return [name for item in _load_cleanup_manifests(root)
            for name in item.get("task_names", []) if isinstance(name, str)]


def _validate_cleanup_manifest(root: Path, manifest: Dict[str, Any]) -> None:
    phase_root = Path(str(manifest.get("root", ""))).resolve(strict=False)
    runs_root = (root / "runs").resolve(strict=False)
    names = manifest.get("task_names")
    if (phase_root == runs_root or runs_root not in phase_root.parents or
            _is_reparse_point(phase_root) or not phase_root.is_absolute()):
        raise RuntimeError("cleanup manifest phase root escapes the H4 run directory")
    if (not isinstance(names, list) or len(names) != 3 or
            any(not isinstance(name, str) or not name.startswith("ResourceCoordinator-H4-") for name in names) or
            len(set(names)) != len(names)):
        raise RuntimeError("cleanup manifest task identities are invalid")
    port = manifest.get("port")
    if type(port) is not int or port in {0, 1235} or not 1024 <= port <= 65535:
        raise RuntimeError("cleanup manifest listener identity is invalid")
    if manifest.get("phase") not in {"install", "upgrade", "rollback"}:
        raise RuntimeError("cleanup manifest phase is invalid")


def _append_cleanup_manifest(root: Path, manifest: Dict[str, Any]) -> None:
    """Persist exact owned phase resources before any task or process mutation."""
    _validate_cleanup_manifest(root, manifest)
    phases = _load_cleanup_manifests(root)
    all_names = {name for item in phases for name in item.get("task_names", [])
                 if isinstance(name, str)}
    if all_names.intersection(manifest["task_names"]):
        raise RuntimeError("duplicate cleanup task identity")
    if any(item.get("phase") == manifest["phase"] or item.get("root") == manifest["root"]
           for item in phases):
        raise RuntimeError("duplicate cleanup phase identity")
    phases.append(dict(manifest))
    root.mkdir(parents=True, exist_ok=True)
    target = root / "cleanup-manifest.json"
    temporary = target.with_name(target.name + ".new")
    if temporary.exists() or (target.exists() and _is_reparse_point(target)):
        raise RuntimeError("cleanup manifest target has an unexpected existing or reparse artifact")
    temporary.write_text(json.dumps({"schema_version": 1, "phases": phases}, indent=2,
                                    sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def _initialize_artifacts(root: Path, environment: Dict[str, Any], preflight: Dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "upgrade-receipts").mkdir(exist_ok=True)
    (root / "task-snapshots").mkdir(exist_ok=True)
    marker = root / ".h4-test-root.json"
    if not marker.exists():
        _write_json(marker, {"schema_version": 1, "root_id": uuid.uuid4().hex, "created_at": _now()})
    _write_json(root / "environment.json", environment)
    _write_json(root / "preflight.json", preflight)
    for filename, status in (
        ("test-results.json", "not_run"), ("process-identity.json", "not_run"),
        ("rollback-result.json", "not_run"), ("cleanup-result.json", "not_run"),
    ):
        path = root / filename
        if not path.exists():
            _write_json(path, {"schema_version": 1, "status": status})


def _available_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    if port == 1235:
        raise RuntimeError("ephemeral port selection returned the production Coordinator port")
    return port


def _repository_roots(
    source_root: Path,
    old_source_root: Optional[Path],
    *,
    source_manifest: Optional[Path] = None,
) -> tuple:
    manifest = load_source_manifest(source_manifest) if source_manifest is not None else None
    new_entry = manifest_entry_for_role(manifest, "new_1_0_0") if manifest is not None else None
    old_entry = (
        manifest_entry_for_role(manifest, "old_0_14_0")
        if manifest is not None and old_source_root is not None
        else None
    )
    new_info = verify_source_tree(
        source_root, expected_version="1.0.0", expected_role="new_1_0_0", manifest_entry=new_entry,
    )
    new_root, new_digest = Path(new_info["source_root"]), new_info["source_tree_sha256"]
    if old_source_root is not None:
        old_info = verify_source_tree(
            old_source_root, expected_version="0.14.0", expected_role="old_0_14_0", manifest_entry=old_entry,
        )
        old_root, old_digest = Path(old_info["source_root"]), old_info["source_tree_sha256"]
    else:
        old_root, old_digest = None, None
    if old_root and old_root == new_root:
        raise SourceIntegrityError(
            "source_roots_identical",
            "old and new source roots must be different immutable source trees",
        )
    return new_root, old_root, new_digest, old_digest


def _isolated_service_config(template: Path, root: Path, port: int) -> None:
    import yaml

    value = yaml.safe_load(template.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("configuration template must contain a mapping")
    service = value.setdefault("service", {})
    if not isinstance(service, dict):
        raise RuntimeError("configuration template service section is malformed")
    service["listen_host"] = "127.0.0.1"
    service["listen_port"] = port
    service["upstream_url"] = "http://127.0.0.1:1"
    service["state_persistence_path"] = str(root / "coordinator_state.json")
    value["processes"] = {}
    root.mkdir(parents=True, exist_ok=True)
    config = root / "config.yaml"
    if config.exists():
        raise RuntimeError("refusing to overwrite an existing phase configuration")
    config.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8", newline="\n")


def _run_guest_lifecycle(profile: str, root: Path, source_root: Path,
                         old_source_root: Optional[Path], timeout_seconds: int,
                         fault_stage: Optional[str]) -> Dict[str, Any]:
    if profile not in {"install", "upgrade", "rollback", "full"}:
        raise RuntimeError("unsupported guest lifecycle profile")
    if profile != "install" and old_source_root is None:
        raise RuntimeError("upgrade, rollback, and full profiles require a staged RC 0.14.0 source root")
    if profile == "rollback" and fault_stage not in FAULT_STAGES:
        raise RuntimeError("rollback profile requires a supported bounded upgrade fault point")
    new_root, old_root, new_digest, old_digest = _repository_roots(source_root, old_source_root)
    if os.name != "nt":
        raise RuntimeError("guest lifecycle profiles execute only on Windows")
    # Import from the explicitly selected 1.0.0 source bundle, never from an installed package.
    module_root = new_root / "modules" / "resource_coordinator"
    sys.path.insert(0, str(module_root))
    from resource_coordinator.installation import (
        InstallationPaths, InstallationRuntime, ManagedInstallation, WindowsStartupTaskBackend,
    )
    if Path(sys.modules["resource_coordinator.installation"].__file__).resolve() != (
            module_root / "resource_coordinator" / "installation.py").resolve():
        raise RuntimeError("Resource Coordinator installer import did not resolve from the selected source bundle")

    marker = json.loads((root / ".h4-test-root.json").read_text(encoding="utf-8"))
    run_id = str(marker.get("root_id", ""))[:10]
    if len(run_id) != 10:
        raise RuntimeError("H4 root marker is invalid")
    phases = ["install"] if profile == "install" else ["upgrade"] if profile == "upgrade" else [
        "rollback"] if profile == "rollback" else ["install", "upgrade", "rollback"]
    results = []
    for phase in phases:
        phase_root = root / "runs" / f"{run_id}-{phase}"
        if phase_root.exists() and any(phase_root.iterdir()):
            raise RuntimeError(f"phase root already has state; refusing implicit adoption: {phase_root}")
        phase_root.mkdir(parents=True, exist_ok=True)
        port = _available_loopback_port()
        template_root = old_root if phase != "install" else new_root
        assert template_root is not None
        _isolated_service_config(template_root / "modules" / "resource_coordinator" /
                                 "config.production-template.yaml", phase_root, port)
        names = {
            "boot": f"ResourceCoordinator-H4-{run_id}-{phase}-boot",
            "logon": f"ResourceCoordinator-H4-{run_id}-{phase}-logon",
            "viewer": f"ResourceCoordinator-H4-{run_id}-{phase}-viewer",
        }
        gate = GuestMutationGate(root, tuple(names.values()), listener_port=port)
        credentials = GuestCredentialProvider(phase_root)
        stage_failure = (fault_stage or "after_task_replacement") if phase == "rollback" else None
        runtime = InstallationRuntime(
            task_names=names, coordinator_url=f"http://127.0.0.1:{port}", listen_port=port,
            guest_mutation_guard=gate, credential_provider=credentials,
            fault_injector=(lambda stage, selected=stage_failure: (_raise_injected(stage)
                                if selected == stage else None)) if stage_failure else None,
        )
        paths = InstallationPaths.isolated(root=phase_root, repository=new_root, python=Path(sys.executable))
        backend = WindowsStartupTaskBackend(
            managed_root=phase_root / "task-helper", task_names=names, guest_mutation_guard=gate,
        )
        current = ManagedInstallation(paths, backend, runtime=runtime)
        task_manifest = {"schema_version": 1, "run_id": run_id, "phase": phase,
                         "task_names": list(names.values()), "root": str(phase_root), "port": port,
                         "source_tree_sha256": new_digest, "old_source_tree_sha256": old_digest}
        _append_cleanup_manifest(root, task_manifest)
        operation_result: Dict[str, Any]
        if phase == "install":
            operation_result = current.setup(apply=True, mode="logon", activate=True)
            service = current._service_status()
            identity = ((service or {}).get("runtime") or {})
            expected_package = new_root / "modules" / "resource_coordinator" / "resource_coordinator"
            if (not service or service.get("service_state") != "ready" or
                    Path(str(identity.get("source_path", ""))).resolve() != expected_package.resolve()):
                raise RuntimeError("fresh install did not start the selected v1.0.0 source as a ready Coordinator")
        else:
            if old_root is None:
                raise RuntimeError("old source root disappeared after preflight")
            old_paths = InstallationPaths.isolated(root=phase_root, repository=old_root, python=Path(sys.executable))
            old = ManagedInstallation(old_paths, backend, template=old_root / "modules" /
                                      "resource_coordinator" / "config.production-template.yaml", runtime=runtime)
            old.setup(apply=True, mode="logon", activate=True)
            old_status = old._service_status()
            identity = ((old_status or {}).get("runtime") or {})
            old_package = old_root / "modules" / "resource_coordinator" / "resource_coordinator"
            if (not old_status or old_status.get("service_state") != "ready" or
                    Path(str(identity.get("source_path", ""))).resolve() != old_package.resolve() or
                    type(identity.get("pid")) is not int or
                    type(identity.get("process_create_time")) not in (int, float)):
                raise RuntimeError("old Coordinator runtime identity was not independently verified")
            gate.allow_process(pid=identity["pid"], creation_time=float(identity["process_create_time"]),
                               executable_path=paths.python)
            process_identity = {
                "schema_version": 1, "phase": phase, "pid": identity["pid"],
                "creation_time": identity["process_create_time"], "executable": paths.python.name,
                "source_version": "0.14.0", "source_root": str(old_root),
            }
            _write_json(phase_root / "process-identity.json", process_identity)
            _write_json(root / "process-identity.json", process_identity)
            if phase == "rollback":
                try:
                    current.upgrade(apply=True, timeout=float(timeout_seconds))
                    operation_result = {"status": "unexpected_success", "phase": phase}
                except Exception as exc:
                    operation_result = {"status": "upgrade_failure_injected", "phase": phase,
                                        "error_type": type(exc).__name__}
                receipt = json.loads(paths.upgrade_receipt.read_text(encoding="utf-8")) if paths.upgrade_receipt.is_file() else {}
                rollback = receipt.get("automatic_rollback") or {}
                if rollback.get("status") not in {"restored", "verified", "ready", "applied"}:
                    raise RuntimeError("injected upgrade failure did not produce a verified automatic rollback")
                _write_json(root / "rollback-result.json", {"schema_version": 1, "status": "passed",
                    "failed_at": receipt.get("failed_at"), "automatic_rollback": rollback})
            else:
                operation_result = current.upgrade(apply=True, timeout=float(timeout_seconds))
                if operation_result.get("status") != "verified":
                    raise RuntimeError("actual 0.14.0 to 1.0.0 upgrade did not reach verified completion")
            _write_json(root / "upgrade-receipts" / f"{phase}.json",
                        json.loads(paths.upgrade_receipt.read_text(encoding="utf-8")))
            _write_json(root / "task-snapshots" / f"{phase}.json",
                        (json.loads(paths.upgrade_receipt.read_text(encoding="utf-8"))).get("task_snapshot", {}))
            final_status = current._service_status()
            final_identity = ((final_status or {}).get("runtime") or {})
            if type(final_identity.get("pid")) is int and type(final_identity.get("process_create_time")) in (int, float):
                gate.allow_process(pid=final_identity["pid"],
                                   creation_time=float(final_identity["process_create_time"]),
                                   executable_path=paths.python)
        final_status = current._service_status()
        final_identity = ((final_status or {}).get("runtime") or {})
        if type(final_identity.get("pid")) is int and type(final_identity.get("process_create_time")) in (int, float):
            gate.allow_process(pid=final_identity["pid"],
                               creation_time=float(final_identity["process_create_time"]),
                               executable_path=paths.python)
            process_identity = {
                "schema_version": 1, "phase": phase, "pid": final_identity["pid"],
                "creation_time": final_identity["process_create_time"], "executable": paths.python.name,
                "source_version": "0.14.0" if phase == "rollback" else "1.0.0",
                "source_root": str(old_root if phase == "rollback" else new_root),
            }
            _write_json(phase_root / "process-identity.json", process_identity)
            _write_json(root / "process-identity.json", process_identity)
        cleanup_status = "not_attempted"
        try:
            cleanup = current.teardown(apply=True, non_interactive=True)
            cleanup_status = str(cleanup.get("status", "unknown"))
            remaining = backend.status()
            if remaining:
                raise RuntimeError("test-owned Scheduled Tasks remain after teardown")
            listener = runtime.listener_details()
            if listener.get("category") != "not-found" or current._service_status() is not None:
                raise RuntimeError("test Coordinator listener or service remains after teardown")
            if type(final_identity.get("pid")) is int and type(final_identity.get("process_create_time")) in (int, float):
                if current._process_alive(final_identity["pid"], float(final_identity["process_create_time"])) is not False:
                    raise RuntimeError("test Coordinator process termination is not independently verified")
            _write_json(root / "cleanup-result.json", {
                "schema_version": 1, "status": "verified", "phase": phase,
                "task_names": list(names.values()), "listener": "not-found",
                "process_termination_verified": True, "cleanup_return_status": cleanup_status,
            })
        except Exception as exc:
            cleanup_status = "failed"
            _write_json(root / "cleanup-result.json", {"schema_version": 1, "status": "failed",
                        "phase": phase, "error_type": type(exc).__name__,
                        "remaining_task_names": list(names.values()),
                        "automatic_cleanup_claimed": False})
            raise
        results.append({"phase": phase, "result": operation_result, "cleanup": cleanup_status,
                        "task_names": list(names.values()), "port": port})
    verified_new_root, verified_old_root, final_new_digest, final_old_digest = _repository_roots(
        source_root, old_source_root
    )
    if (verified_new_root != new_root or verified_old_root != old_root or
            final_new_digest != new_digest or final_old_digest != old_digest):
        raise RuntimeError("source bundle identity changed during guest lifecycle acceptance")
    return {"schema_version": 1, "status": "passed", "profile": profile,
            "source_version": "1.0.0", "old_source_version": "0.14.0" if old_root else None,
            "source_tree_sha256": new_digest, "old_source_tree_sha256": old_digest,
            "phases": results, "completed_at": _now()}


def _run_guest_cleanup(root: Path, source_root: Path) -> Dict[str, Any]:
    new_root, _, source_digest, _ = _repository_roots(source_root, None)
    manifests = _load_cleanup_manifests(root)
    if not manifests:
        raise RuntimeError("no exact test-owned cleanup manifest is available")
    module_root = new_root / "modules" / "resource_coordinator"
    sys.path.insert(0, str(module_root))
    from resource_coordinator.installation import InstallationPaths, InstallationRuntime, ManagedInstallation, WindowsStartupTaskBackend
    if Path(sys.modules["resource_coordinator.installation"].__file__).resolve() != (
            module_root / "resource_coordinator" / "installation.py").resolve():
        raise RuntimeError("cleanup imported installer source differs from the pinned test source")
    results = []
    for manifest in reversed(manifests):
        _validate_cleanup_manifest(root, manifest)
        if manifest.get("source_tree_sha256") != source_digest:
            raise RuntimeError("cleanup source bundle differs from the source recorded before mutation")
        phase_root = Path(manifest["root"]).resolve(strict=True)
        names = manifest["task_names"]
        name_map = {"boot": names[0], "logon": names[1], "viewer": names[2]}
        port = manifest["port"]
        gate = GuestMutationGate(root, names, listener_port=port)
        runtime = InstallationRuntime(task_names=name_map, coordinator_url=f"http://127.0.0.1:{port}",
                                      listen_port=port, guest_mutation_guard=gate,
                                      credential_provider=GuestCredentialProvider(phase_root))
        paths = InstallationPaths.isolated(root=phase_root, repository=new_root, python=Path(sys.executable))
        backend = WindowsStartupTaskBackend(managed_root=phase_root / "task-helper", task_names=name_map,
                                            guest_mutation_guard=gate)
        manager = ManagedInstallation(paths, backend, runtime=runtime)
        identity_path = phase_root / "process-identity.json"
        identity = json.loads(identity_path.read_text(encoding="utf-8")) if identity_path.is_file() else {}
        status = manager._service_status()
        observed = (status or {}).get("runtime") or {}
        if type(observed.get("pid")) is int and type(observed.get("process_create_time")) in (int, float):
            identity = {"phase": manifest["phase"], "pid": observed["pid"],
                        "creation_time": observed["process_create_time"]}
            _write_json(identity_path, identity)
        process_records = []
        if (identity.get("phase") == manifest["phase"] and type(identity.get("pid")) is int and
                type(identity.get("creation_time")) in (int, float)):
            gate.allow_process(pid=identity["pid"], creation_time=float(identity["creation_time"]),
                               executable_path=paths.python)
            process_records.append(identity)
        if status is not None or backend.status():
            cleanup_result = manager.teardown(apply=True, non_interactive=True)
        else:
            cleanup_result = {"status": "already-stopped"}
        remaining = [asdict(task) for task in backend.status()]
        if remaining:
            raise RuntimeError("exact test-owned Tasks remain after cleanup reconciliation")
        listener = runtime.listener_details()
        if listener.get("category") != "not-found" or manager._service_status() is not None:
            raise RuntimeError("Coordinator listener remains after cleanup reconciliation")
        for process in process_records:
            if manager._process_alive(process["pid"], float(process["creation_time"])) is not False:
                raise RuntimeError("test Coordinator process termination remains uncertain after cleanup")
        results.append({"phase": manifest["phase"], "status": "verified", "task_names": names,
                        "remaining_tasks": remaining, "listener": "not-found",
                        "process_termination_verified": True,
                        "cleanup_return_status": cleanup_result.get("status", "unknown")})
    return {"schema_version": 1, "status": "verified", "phases": results,
            "source_tree_sha256": source_digest, "completed_at": _now()}


def _raise_injected(stage: str) -> None:
    raise RuntimeError("H4 test-only injected upgrade failure at " + stage)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-r", "--test-root", required=True, type=Path,
                        help="Absolute, guest-local directory beginning h4-rc-")
    parser.add_argument("-a", "--apply", action="store_true", help="Run the selected explicitly gated integration profile")
    parser.add_argument("-p", "--profile", choices=("preflight", "offline", "task", "install", "upgrade", "rollback", "full", "cleanup"), default="preflight",
                        help="preflight is read-only; install/upgrade/rollback/full mutate only a separately authorized guest")
    parser.add_argument("-A", "--authorization", help="Must exactly equal the H4 disposable-test authorization phrase")
    parser.add_argument("-G", "--authorize-guest-mutation", action="store_true",
                        help="Explicitly authorize mutations in the independently verified disposable guest")
    parser.add_argument("-S", "--source-root", type=Path, default=Path(__file__).resolve().parents[4],
                        help="Absolute staged RC 1.0.0 source repository")
    parser.add_argument("-O", "--old-source-root", type=Path,
                        help="Absolute staged RC 0.14.0 source repository for upgrade/rollback/full")
    parser.add_argument("-M", "--source-manifest", type=Path,
                        help="Pinned source/bundle manifest JSON enforcing canonical tree digests")
    parser.add_argument("-F", "--fault-stage", choices=FAULT_STAGES,
                        help="Bounded upgrade interruption point used by rollback/full guest profiles")
    parser.add_argument("-j", "--json", action="store_true", help="Print a machine-readable result")
    parser.add_argument("-T", "--timeout-seconds", type=int, default=900,
                        help="Bounded pytest timeout (30-1800 seconds)")
    return parser


def main(argv: Optional[Sequence[str]] = None, *, evidence_override: Optional[Dict[str, Any]] = None,
         is_windows: Optional[bool] = None, lifecycle_runner_override=None,
         python_version_info: Optional[Sequence[int]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        require_supported_python("windows_acceptance", version_info=python_version_info)
    except PythonCompatibilityError as exc:
        payload = {"status": "failed", "reason_code": exc.code, "error": str(exc), "details": exc.details}
        print(json.dumps(payload, sort_keys=True) if args.json else str(exc), file=sys.stderr)
        return 2
    is_windows = os.name == "nt" if is_windows is None else is_windows
    guest_profiles = {"task", "install", "upgrade", "rollback", "full", "cleanup"}
    lifecycle_profiles = {"install", "upgrade", "rollback", "full"}
    if args.profile == "preflight" and args.apply:
        print("preflight is read-only; select a mutation profile explicitly", file=sys.stderr)
        return 2
    unresolved_root = args.test_root.expanduser()
    if not unresolved_root.is_absolute() or not unresolved_root.is_dir():
        print("--test-root must be an existing absolute directory created for this H4 run", file=sys.stderr)
        return 2
    path_chain = [unresolved_root, *unresolved_root.parents]
    has_reparse_parent = any(_is_reparse_point(path) for path in path_chain if path.exists())
    test_root = unresolved_root.resolve()
    if not 30 <= args.timeout_seconds <= 1800:
        print("timeout must be between 30 and 1800 seconds", file=sys.stderr)
        return 2
    if args.apply and args.profile in guest_profiles and (
            args.authorization != AUTHORIZATION_PHRASE or not args.authorize_guest_mutation or
            os.environ.get("RC_H4_DISPOSABLE_GUEST_AUTHORIZED") != AUTHORIZATION_PHRASE):
        print("guest mutation requires --apply, -G, the authorization phrase, and RC_H4_DISPOSABLE_GUEST_AUTHORIZED", file=sys.stderr)
        return 2
    try:
        evidence = evidence_override if evidence_override is not None else (
            _run_powershell(test_root=test_root) if is_windows else {"queries": {"system": "unavailable"}}
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        evidence = {"queries": {"system": "error"}, "errors": [type(exc).__name__]}
    cleanup_tasks: Sequence[str] = ()
    cleanup_processes: Sequence[Dict[str, Any]] = ()
    if args.profile == "cleanup":
        try:
            manifests = _load_cleanup_manifests(test_root)
            cleanup_tasks = [name for manifest in manifests for name in manifest.get("task_names", [])
                             if isinstance(name, str)]
            records = []
            for manifest in manifests:
                _validate_cleanup_manifest(test_root, manifest)
                phase_root = Path(manifest["root"]).resolve(strict=True)
                identity_path = phase_root / "process-identity.json"
                if identity_path.is_file():
                    identity = json.loads(identity_path.read_text(encoding="utf-8"))
                    if (identity.get("phase") == manifest.get("phase") and type(identity.get("pid")) is int and
                            type(identity.get("creation_time")) in (float, int)):
                        records.append({
                            "pid": identity["pid"], "creation_time": identity["creation_time"],
                            "executable_path": str(Path(sys.executable).resolve()).casefold(),
                        })
            cleanup_processes = records
        except (OSError, ValueError, TypeError):
            pass
    observed_reasons = guard_reasons(evidence, test_root, is_windows=is_windows,
                                     owned_task_names=cleanup_tasks,
                                     owned_processes=cleanup_processes)
    reasons = list(observed_reasons)
    if not unresolved_root.is_absolute():
        reasons.append("test_root_must_be_absolute")
    if has_reparse_parent:
        reasons.append("test_root_path_contains_reparse_point")
    if args.profile in guest_profiles:
        reasons.extend(task_path_reasons(test_root))
    if not (test_root / ".h4-test-root.json").exists() and any(test_root.iterdir()):
        print("unmarked test root is not empty; refusing to adopt existing artifacts", file=sys.stderr)
        return 2
    if any(item.name not in {
        ".h4-test-root.json", "environment.json", "preflight.json", "test-results.json",
        "process-identity.json", "rollback-result.json", "cleanup-result.json", "cleanup-manifest.json",
        "pytest-output.log", "upgrade-receipts", "task-snapshots",
        "runs", "junit.xml",
    } and not item.name.startswith(("pytest-temp-", "junit-")) for item in test_root.iterdir()):
        print("test root contains unrecognized artifacts; refusing to write or run", file=sys.stderr)
        return 2
    if any(_is_reparse_point(item) for item in test_root.iterdir()):
        print("test root contains a reparse-point artifact; refusing to write or run", file=sys.stderr)
        return 2
    protected_roots = [Path.home() / ".resource_coordinator", Path(os.environ.get("ProgramData", "C:/ProgramData"))]
    if any(test_root == candidate.resolve() or candidate.resolve() in test_root.parents for candidate in protected_roots):
        reasons.append("test_root_overlaps_protected_installation_path")
    if args.apply and args.profile == "offline":
        # This profile is mock-backed and cannot register tasks, control processes,
        # or access GPU/runtime APIs. It is safe to run on the development host.
        reasons = [reason for reason in reasons if reason not in {
            "not_windows", "guest_identity_not_independently_verified", "tasks_inventory_unavailable",
            "services_inventory_unavailable", "processes_inventory_unavailable", "rc_task_present",
            "rc_service_present", "rc_or_miner_process_present",
        }]
    elif args.apply and not reasons and args.profile in guest_profiles:
        # A guest mutation is permitted only after independent guest and inventory checks.
        pass
    source_integrity: Optional[Dict[str, Any]] = None
    if args.source_manifest is not None:
        try:
            new_root, old_root, new_digest, old_digest = _repository_roots(
                args.source_root, args.old_source_root, source_manifest=args.source_manifest,
            )
            source_integrity = {
                "verified": True,
                "hash_algorithm": HASH_ALGORITHM,
                "source_root": str(new_root),
                "source_tree_sha256": new_digest,
                "old_source_root": str(old_root) if old_root else None,
                "old_source_tree_sha256": old_digest,
            }
        except SourceIntegrityError as exc:
            source_integrity = {
                "verified": False,
                "reason_code": exc.code,
                "error": str(exc),
            }
            reasons.append(f"source_integrity:{exc.code}")
    elif args.profile in lifecycle_profiles or (args.profile == "task" and args.apply):
        source_integrity = {
            "verified": False,
            "reason_code": "source_manifest_required",
            "error": "Guest task and lifecycle profiles require a pinned --source-manifest",
        }
        reasons.append("source_manifest_required")
    elif args.profile == "task":
        try:
            new_root, _, new_digest, _ = _repository_roots(args.source_root, None)
            source_integrity = {
                "verified": True,
                "mode": "task_source_tree_only",
                "hash_algorithm": HASH_ALGORITHM,
                "source_root": str(new_root),
                "source_tree_sha256": new_digest,
            }
        except SourceIntegrityError as exc:
            source_integrity = {"verified": False, "reason_code": exc.code, "error": str(exc)}
            reasons.append(f"source_integrity:{exc.code}")
    else:
        source_integrity = {
            "verified": False,
            "mode": "diagnostic_unpinned",
        }
    preflight = {
        "schema_version": 1, "observed_at": _now(), "guest_verified": bool(
            is_windows and guest_identity(evidence)
        ), "profile_ready": not reasons,
        "mutation_ready": args.profile in guest_profiles and not reasons,
        "profile": args.profile, "apply_requested": args.apply,
        "observed_guard_reasons": observed_reasons, "profile_blockers": reasons,
        "source_integrity": source_integrity,
    }
    _initialize_artifacts(test_root, evidence, preflight)
    if not args.apply:
        value = {"status": "preflight_only", **preflight}
        print(json.dumps(value, sort_keys=True) if args.json else
              f"H4 preflight only: guest_verified={value['guest_verified']}; "
              f"mutation_ready={value['mutation_ready']}; reasons={','.join(reasons) or 'none'}")
        return 0 if not reasons else 3
    if reasons:
        print(json.dumps({"status": "refused", "guard_reasons": reasons}, sort_keys=True), file=sys.stderr)
        return 3
    if args.profile == "offline":
        targets = ["tests/test_installation.py", "tests/test_windows_task_transport_integration.py::test_windows_helper_processes_large_request_from_protected_file"]
        env_name = None
    elif args.profile == "task":
        targets = ["tests/test_windows_task_transport_integration.py::test_windows_disposable_task_registration_snapshot_restore_and_verification"]
        env_name = "RC_WINDOWS_TASK_INTEGRATION"
    else:
        targets = []
        env_name = None
    env = os.environ.copy()
    selected_module_root = (
        args.source_root.expanduser().resolve() / "modules" / "resource_coordinator"
        if args.source_root is not None
        else Path(__file__).resolve().parents[2]
    )
    metrics_root = selected_module_root.parent / "resource_metrics"
    pythonpath_entries = [str(selected_module_root)]
    if metrics_root.is_dir():
        pythonpath_entries.append(str(metrics_root))
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    if env_name:
        env[env_name] = "1"
        env["RC_H4_TEST_ROOT"] = str(test_root)
        env["RC_H4_AUTHORIZATION"] = AUTHORIZATION_PHRASE
    if args.profile in lifecycle_profiles | {"cleanup"}:
        gate = GuestMutationGate(test_root, ())
        try:
            lifecycle_runner = lifecycle_runner_override or _run_guest_lifecycle
            if args.profile == "cleanup":
                outcome = _run_guest_cleanup(test_root, args.source_root)
                _write_json(test_root / "cleanup-result.json", outcome)
            else:
                gate()
                outcome = lifecycle_runner(args.profile, test_root, args.source_root,
                                           args.old_source_root, args.timeout_seconds, args.fault_stage)
            outcome = {"schema_version": 1, **outcome, "exit_code": 0,
                       "completed_at": _now()}
            _write_json(test_root / "test-results.json", outcome)
            junit = ET.Element("testsuite", {"name": "h4_guest_lifecycle", "tests": str(len(outcome.get("phases", []))),
                                               "failures": "0", "errors": "0", "skipped": "0"})
            ET.ElementTree(junit).write(test_root / "junit.xml", encoding="utf-8", xml_declaration=True)
            print(json.dumps(outcome, sort_keys=True) if args.json else
                  f"H4 {args.profile} profile: passed; results={test_root / 'test-results.json'}")
            return 0
        except Exception as exc:
            diag_stage = getattr(exc, "stage", "preflight")
            diag_reason = getattr(exc, "reason_code", type(exc).__name__)
            diag_guards = list(getattr(exc, "guard_reasons", ()))
            outcome = {
                "schema_version": 1,
                "profile": args.profile,
                "status": "failed",
                "exit_code": 4,
                "stage": diag_stage,
                "reason_code": diag_reason,
                "guard_reasons": diag_guards,
                "completed_at": _now(),
            }
            _write_json(test_root / "test-results.json", outcome)
            suite = ET.Element("testsuite", {"name": "h4_guest_lifecycle", "tests": "1",
                                               "failures": "0", "errors": "1", "skipped": "0"})
            case = ET.SubElement(suite, "testcase", {"classname": "h4_guest_lifecycle",
                                                      "name": str(args.profile)})
            error = ET.SubElement(case, "error", {"type": diag_reason,
                                                   "message": "guest lifecycle failed; inspect bounded JSON evidence"})
            error.text = "No exception text is stored because it may contain host-specific arguments or paths."
            ET.ElementTree(suite).write(test_root / "junit.xml", encoding="utf-8", xml_declaration=True)
            _write_json(test_root / "cleanup-result.json", {
                "schema_version": 1, "status": "requires_review", "automatic_cleanup_claimed": False,
                "exact_task_names": _manifest_task_names(test_root),
                "stage": diag_stage,
                "reason_code": diag_reason,
                "guard_reasons": diag_guards,
            })
            print(json.dumps(outcome, sort_keys=True) if args.json else
                  f"H4 {args.profile} profile: failed safely ({type(exc).__name__}); inspect {test_root / 'test-results.json'}",
                  file=sys.stderr)
            return 4
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    pytest_temp = test_root / f"pytest-temp-{run_id}"
    junit = test_root / f"junit-{run_id}.xml"
    pytest_log = test_root / "pytest-output.log"
    command = [sys.executable, "-m", "pytest", *targets, "-q",
               "--basetemp", str(pytest_temp), "--junitxml", str(junit)]
    try:
        result = subprocess.run(command, cwd=selected_module_root, env=env,
                                timeout=args.timeout_seconds + 30, check=False, capture_output=True, text=True)
        pytest_log.write_text((result.stdout or "") + (result.stderr or ""), encoding="utf-8")
        counts: Dict[str, int] = {}
        if junit.is_file():
            root = ET.parse(junit).getroot()
            suite_nodes = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
            for node in suite_nodes:
                for key in ("tests", "failures", "errors", "skipped"):
                    counts[key] = counts.get(key, 0) + int(node.attrib.get(key, 0))
        if not junit.is_file():
            status, exit_code = "junit_missing", 4
        elif result.returncode != 0:
            status, exit_code = "failed", result.returncode
        elif args.profile == "task" and counts.get("skipped", 0):
            status, exit_code = "skipped", 5
        else:
            status, exit_code = "passed", 0
        outcome = {"schema_version": 1, "status": status, "exit_code": exit_code,
                   "profile": args.profile, "junit": str(junit), "log": str(pytest_log), "counts": counts,
                   "completed_at": _now()}
    except subprocess.TimeoutExpired:
        pytest_log.write_text("pytest subprocess exceeded configured timeout\n", encoding="utf-8")
        outcome = {"schema_version": 1, "status": "timeout", "exit_code": 124,
                   "profile": args.profile, "junit": str(junit), "log": str(pytest_log),
                   "completed_at": _now()}
    _write_json(test_root / "test-results.json", outcome)
    cleanup = {
        "schema_version": 1,
        "status": "task_cleanup_asserted_by_test" if args.profile == "task" and outcome["status"] == "passed"
        else "requires_review" if args.profile == "task" else "not_applicable",
        "evidence": "pytest finally-block and post-delete verification" if args.profile == "task" else None,
    }
    if args.profile == "task" and outcome["exit_code"] != 0:
        cleanup["exact_cleanup_manifest"] = str(test_root / "cleanup-manifest.json")
        cleanup["automatic_cleanup_claimed"] = False
    _write_json(test_root / "cleanup-result.json", cleanup)
    print(json.dumps(outcome, sort_keys=True) if args.json else
          f"H4 {args.profile} profile: {outcome['status']} (exit {outcome['exit_code']}); junit={junit}")
    return int(outcome["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
