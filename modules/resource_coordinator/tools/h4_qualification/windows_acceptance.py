#!/usr/bin/env python3
"""Fail-closed launcher for isolated Windows H4 checks.

Default operation is a read-only preflight plus artifact initialization. The
only mutating profile currently exposed is the existing disposable Task
Scheduler/helper integration test; it requires independently observed guest
identity and an explicit operator authorization phrase.
"""

import argparse
import json
import os
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


AUTHORIZATION_PHRASE = "I AUTHORIZE DISPOSABLE H4 WINDOWS MUTATION"
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


def _run_powershell() -> Dict[str, Any]:
    shell = next((candidate for candidate in ("pwsh.exe", "powershell.exe")
                  if _which(candidate)), None)
    if shell is None:
        raise RuntimeError("PowerShell is unavailable")
    script = r"""
$ErrorActionPreference = 'Stop'
$result = [ordered]@{schema_version=1; queries=[ordered]@{}}
try {
  $cs = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
  $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
  $result.computer = @{manufacturer=[string]$cs.Manufacturer; model=[string]$cs.Model; hypervisor_present=[bool]$cs.HypervisorPresent}
  $result.os = @{caption=[string]$os.Caption; version=[string]$os.Version; build=[string]$os.BuildNumber}
  $result.queries.system = 'available'
} catch { $result.queries.system = 'error'; $result.errors = @("system_query:$($_.Exception.GetType().Name)") }
try {
  $tasks = @(Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.TaskName -match 'ResourceCoordinator|KRig-Live-Output-Viewer|^RC-Disposable-' } | ForEach-Object { @{name=[string]$_.TaskName; state=[string]$_.State} })
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
  } | ForEach-Object { @{name=[string]$_.Name; pid=[int]$_.ProcessId} })
  $result.rc_processes = $matches
  $result.queries.processes = 'available'
} catch { $result.queries.processes = 'error'; $result.errors += "process_query:$($_.Exception.GetType().Name)" }
$result | ConvertTo-Json -Depth 6 -Compress
"""
    completed = subprocess.run(
        [shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=20, check=False,
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


def guard_reasons(evidence: Dict[str, Any], test_root: Path, *, is_windows: bool) -> list:
    reasons = []
    if not is_windows:
        reasons.append("not_windows")
    if not guest_identity(evidence):
        reasons.append("guest_identity_not_independently_verified")
    queries = evidence.get("queries", {})
    for key in ("tasks", "services", "processes"):
        if queries.get(key) != "available":
            reasons.append(f"{key}_inventory_unavailable")
    if evidence.get("rc_tasks"):
        reasons.append("rc_task_present")
    if evidence.get("rc_services"):
        reasons.append("rc_service_present")
    if evidence.get("rc_processes"):
        reasons.append("rc_or_miner_process_present")
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
    allowed_names = {
        ".h4-test-root.json", "environment.json", "preflight.json", "test-results.json",
        "process-identity.json", "rollback-result.json", "cleanup-result.json", "cleanup-manifest.json",
        "pytest-output.log", "upgrade-receipts", "task-snapshots",
    }
    children = list(test_root.iterdir())
    if not (test_root / ".h4-test-root.json").exists() and children:
        reasons.append("unmarked_test_root_not_empty")
    if any(child.name not in allowed_names and not child.name.startswith(("pytest-temp-", "junit-"))
           for child in children):
        reasons.append("test_root_contains_unrecognized_artifacts")
    if any(_is_reparse_point(child) for child in children):
        reasons.append("test_root_contains_reparse_point_artifact")
    return reasons


def _write_json(path: Path, value: Dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-r", "--test-root", required=True, type=Path,
                        help="Absolute, guest-local directory beginning h4-rc-")
    parser.add_argument("-a", "--apply", action="store_true", help="Run the selected explicitly gated integration profile")
    parser.add_argument("-p", "--profile", choices=("offline", "task"), default="offline",
                        help="offline runs mock-backed installer tests; task mutates one unique disposable task")
    parser.add_argument("-A", "--authorization", help="Must exactly equal the H4 disposable-test authorization phrase")
    parser.add_argument("-j", "--json", action="store_true", help="Print a machine-readable result")
    parser.add_argument("-T", "--timeout-seconds", type=int, default=900,
                        help="Bounded pytest timeout (30-1800 seconds)")
    return parser


def main(argv: Optional[Sequence[str]] = None, *, evidence_override: Optional[Dict[str, Any]] = None,
         is_windows: Optional[bool] = None) -> int:
    args = build_parser().parse_args(argv)
    is_windows = os.name == "nt" if is_windows is None else is_windows
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
    if args.apply and args.profile == "task" and args.authorization != AUTHORIZATION_PHRASE:
        print("--apply requires the exact disposable-test authorization phrase", file=sys.stderr)
        return 2
    try:
        evidence = evidence_override if evidence_override is not None else (
            _run_powershell() if is_windows else {"queries": {"system": "unavailable"}}
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        evidence = {"queries": {"system": "error"}, "errors": [type(exc).__name__]}
    observed_reasons = guard_reasons(evidence, test_root, is_windows=is_windows)
    reasons = list(observed_reasons)
    if not unresolved_root.is_absolute():
        reasons.append("test_root_must_be_absolute")
    if has_reparse_parent:
        reasons.append("test_root_path_contains_reparse_point")
    if args.profile == "task":
        reasons.extend(task_path_reasons(test_root))
    if not (test_root / ".h4-test-root.json").exists() and any(test_root.iterdir()):
        print("unmarked test root is not empty; refusing to adopt existing artifacts", file=sys.stderr)
        return 2
    if any(item.name not in {
        ".h4-test-root.json", "environment.json", "preflight.json", "test-results.json",
        "process-identity.json", "rollback-result.json", "cleanup-result.json", "cleanup-manifest.json",
        "pytest-output.log", "upgrade-receipts",
        "task-snapshots",
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
    elif args.apply and not reasons and args.profile == "task":
        # A task mutation is permitted only after independent guest and inventory checks.
        pass
    preflight = {
        "schema_version": 1, "observed_at": _now(), "guest_verified": bool(
            is_windows and guest_identity(evidence)
        ), "profile_ready": not reasons,
        "mutation_ready": args.profile == "task" and not reasons,
        "profile": args.profile, "apply_requested": args.apply,
        "observed_guard_reasons": observed_reasons, "profile_blockers": reasons,
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
    else:
        targets = ["tests/test_windows_task_transport_integration.py::test_windows_disposable_task_registration_snapshot_restore_and_verification"]
        env_name = "RC_WINDOWS_TASK_INTEGRATION"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    if env_name:
        env[env_name] = "1"
        env["RC_H4_TEST_ROOT"] = str(test_root)
        env["RC_H4_AUTHORIZATION"] = AUTHORIZATION_PHRASE
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    pytest_temp = test_root / f"pytest-temp-{run_id}"
    junit = test_root / f"junit-{run_id}.xml"
    pytest_log = test_root / "pytest-output.log"
    command = [sys.executable, "-m", "pytest", *targets, "-q",
               "--basetemp", str(pytest_temp), "--junitxml", str(junit)]
    try:
        result = subprocess.run(command, cwd=Path(__file__).resolve().parents[2], env=env,
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
