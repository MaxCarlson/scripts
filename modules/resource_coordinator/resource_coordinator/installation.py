"""Self-managed installation paths and Windows startup-task control."""

from __future__ import annotations

import base64
import csv
import ctypes
import hashlib
import getpass
import json
import math
import os
import psutil
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

import httpx

from resource_coordinator.config import load_config
from resource_coordinator.core.durable_state import RequestPhase, StateCodec
from resource_coordinator.core.lock import SingleInstanceLock
from resource_coordinator.core.processes import ProcessLifecycleOwner
from resource_coordinator.core.operator_credentials import (
    credential_path,
    doctor as credential_doctor,
    load_or_create_token,
    load_token,
)
from resource_coordinator.core.runtime_identity import build_runtime_identity
from resource_coordinator.windows_listener import identify_tcp_listener


TASK_MARKER = "ResourceCoordinator:Managed:v1"
TASK_NAMES = {
    "boot": "ResourceCoordinator-KRig-Boot",
    "logon": "ResourceCoordinator-KRig-UserLogon",
    "viewer": "KRig-Live-Output-Viewer",
}
COORDINATOR_URL = "http://127.0.0.1:1235"


class InstallationError(RuntimeError):
    """A managed setup/startup/teardown operation could not be completed safely."""


class ElevationRequired(InstallationError):
    """A Windows operation needs approval through UAC."""


@dataclass(frozen=True)
class InstallationPaths:
    home: Path
    repository: Path
    python: Path
    root: Path
    config: Path
    state: Path
    token: Path
    logs: Path
    launcher: Path
    viewer: Path
    coordinator_log: Path
    upgrade_receipt: Path
    upgrade_policy: Path

    @classmethod
    def discover(cls, *, home: Optional[Path] = None, repository: Optional[Path] = None,
                 python: Optional[Path] = None) -> "InstallationPaths":
        package = Path(__file__).resolve()
        repo = (repository or package.parents[3]).resolve()
        user_home = (home or Path.home()).resolve()
        root = user_home / ".resource_coordinator"
        config_override = os.environ.get("RESOURCE_COORDINATOR_CONFIG")
        return cls(
            home=user_home,
            repository=repo,
            python=(python or Path(sys.executable)).resolve(),
            root=root,
            config=Path(config_override).expanduser().resolve() if config_override else root / "config.yaml",
            state=root / "coordinator_state.json",
            token=credential_path().resolve(),
            logs=root / "logs",
            launcher=root / "start-coordinator-managed.ps1",
            viewer=root / "view-krig-managed.ps1",
            coordinator_log=root / "coordinator.log",
            upgrade_receipt=root / "upgrade-receipt.json",
            upgrade_policy=root / "upgrade-start-policy.json",
        )


@dataclass(frozen=True)
class StartupTask:
    name: str
    mode: str
    enabled: bool
    state: str
    user_id: str
    run_level: str
    action: str
    owned: bool


class StartupTaskBackend(Protocol):
    def status(self) -> List[StartupTask]: ...

    def install(self, mode: str, launcher: Path, *, non_interactive: bool = False) -> StartupTask: ...

    def install_viewer(self, launcher: Path) -> StartupTask: ...

    def set_enabled(self, task: StartupTask, enabled: bool, *, non_interactive: bool = False) -> StartupTask: ...

    def uninstall(self, task: StartupTask, *, non_interactive: bool = False) -> None: ...

    def start(self, task: StartupTask, *, non_interactive: bool = False) -> None: ...


def _ps_single_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _clean_powershell_error(value: str) -> str:
    """Convert PowerShell's encoded CLIXML stderr into a short actionable message."""
    text = value.replace("_x000D__x000A_", "\n").replace("_x000A_", "\n").strip()
    if "#< CLIXML" in text:
        matches = re.findall(r'Exception calling [^:]+:\s*"([^"]+)"', text)
        if matches:
            return matches[-1].strip()
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
    return text


def _configured_miner(config_path: Path) -> Optional[str]:
    config = load_config(config_path)
    for name, process in config.processes.items():
        if "miner" not in name.casefold() and "krig" not in name.casefold():
            continue
        args = process.arguments
        if "--user" not in args:
            return None
        index = args.index("--user")
        if index + 1 >= len(args):
            return None
        identity = args[index + 1]
        if not identity.strip() or identity.startswith("<") or "YOUR_" in identity.upper():
            return None
        return name
    return None


def _configured_gpu_settings(config: Any) -> Dict[str, float]:
    flags = {
        "--gpu-plimit": "power_limit_w",
        "--gpu-cclock": "core_clock_mhz",
        "--gpu-coffset": "core_offset_mhz",
        "--gpu-mclock": "memory_clock_mhz",
    }
    found: Dict[str, float] = {}
    for process in config.processes.values():
        arguments = process.arguments
        for index, argument in enumerate(arguments[:-1]):
            field = flags.get(argument)
            if field is None:
                continue
            try:
                found[field] = float(arguments[index + 1])
            except (TypeError, ValueError):
                continue
    return found


def _effective_log_path(process_name: str, process: Any, log_directory: Path) -> Path:
    """Resolve the path build_system will use for capture when config omits one."""
    configured = getattr(process, "stdout_log_path", None)
    return Path(configured).expanduser() if configured else log_directory / f"{process_name}.log"


def _runtime_source_matches(runtime_source: Optional[str], expected_source: Path) -> bool:
    if not runtime_source:
        return False
    return os.path.normcase(os.path.realpath(runtime_source)) == os.path.normcase(os.path.realpath(expected_source))


def _same_process_creation_time(reported: Any, observed: Any, *, tolerance: float = 0.01) -> bool:
    """Compare process creation timestamps conservatively; malformed data never matches."""
    try:
        left, right = float(reported), float(observed)
        return math.isfinite(left) and math.isfinite(right) and abs(left - right) <= tolerance
    except (TypeError, ValueError, OverflowError):
        return False


def _write_json_atomic(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _listener_identity_details(port: int = 1235, host: str = "127.0.0.1") -> Dict[str, Any]:
    """Return verifiable listener identity plus diagnostics from both OS backends."""
    return identify_tcp_listener(host, port).to_dict()


def _listener_identity(port: int = 1235, host: str = "127.0.0.1") -> Optional[Dict[str, Any]]:
    """Identify the local listener using OS evidence, not just its HTTP response."""
    result = _listener_identity_details(port, host)
    identity = result.get("identity")
    return identity if result.get("verified") and isinstance(identity, dict) else None


def _listener_failure_reason(result: Dict[str, Any], host: str, port: int) -> str:
    category = result.get("category", "identity-unavailable")
    if category == "not-found":
        summary = f"No listening endpoint matching {host}:{port} was found."
    elif category == "ambiguous":
        summary = f"Multiple process identities match listener port {port}; ownership is ambiguous."
    else:
        summary = f"A listener may exist on port {port}, but its owning process identity could not be verified."
    evidence = [str(item) for item in result.get("diagnostics", []) if item]
    details = "; ".join(evidence[:4])
    return f"{summary}" + (f" Evidence: {details}" if details else "")


def _same_path(left: Any, right: Any) -> bool:
    return bool(left and right) and os.path.normcase(os.path.realpath(str(left))) == os.path.normcase(os.path.realpath(str(right)))


def _option_value(args: List[str], option: str) -> Optional[str]:
    matches = [i for i, value in enumerate(args) if value == option]
    return args[matches[0] + 1] if len(matches) == 1 and matches[0] + 1 < len(args) else None


def verify_legacy_evidence(evidence: Dict[str, Any], miner_name: Optional[str]) -> Dict[str, Any]:
    """Verify a captured task/process chain without exposing process arguments."""
    def fail(reason: str) -> Dict[str, Any]:
        return {"verified": False, "shutdown_verified": False, "reason": reason}

    engines, chain, listener = evidence.get("engine_pids"), evidence.get("chain"), evidence.get("listener") or {}
    if not isinstance(engines, list) or len(engines) != 1 or not engines[0]:
        return fail("Expected exactly one running Scheduled Task instance with an engine PID")
    if not isinstance(chain, list) or len(chain) < 2 or len(chain) > 8:
        return fail("Task-to-listener process ancestry is incomplete")
    if chain[0].get("pid") != listener.get("pid") or not _same_process_creation_time(
            chain[0].get("create_time"), listener.get("create_time")):
        return fail("Listener PID or creation time changed during attribution")
    if not _same_path(chain[0].get("executable"), listener.get("executable")):
        return fail("Listener executable changed during attribution")
    if chain[-1].get("pid") != engines[0]:
        return fail("Listener ancestry does not reach the running task engine")
    for child, parent in zip(chain, chain[1:]):
        if child.get("ppid") != parent.get("pid") or not isinstance(child.get("create_time"), (int, float)) or not isinstance(parent.get("create_time"), (int, float)) or not math.isfinite(child["create_time"]) or not math.isfinite(parent["create_time"]) or parent["create_time"] > child["create_time"]:
            return fail("Process ancestry or creation times are inconsistent")
    engine_args = chain[-1].get("cmdline") or []
    if not _same_path(_option_value([str(x).lower() if str(x).lower() == '-file' else str(x) for x in engine_args], "-file"), evidence.get("launcher")):
        return fail("Task engine command does not identify the expected launcher")
    for process in chain[:-1]:
        args = process.get("cmdline") or []
        executable = Path(str(process.get("executable") or "")).name.casefold()
        if not re.fullmatch(r"python(?:w|[0-9.]*)?\.exe", executable):
            return fail("Service ancestry contains an unexpected executable")
        if not isinstance(args, list) or len(args) < 4 or args[1:4] != ["-m", "resource_coordinator.cli", "serve"]:
            return fail("Process command is not the expected Resource Coordinator service")
        if sum(value in ("-c", "--config") for value in args) != 1:
            return fail("Service configuration argument is missing or ambiguous")
        config = _option_value(args, "-c") or _option_value(args, "--config")
        if not _same_path(config, evidence.get("config")):
            return fail("Service configuration path is missing or differs from the installed configuration")
        if miner_name and _option_value(args, "--stop-process-on-shutdown") != miner_name:
            return fail("Service arguments do not guarantee shutdown of the configured miner")
    return {"verified": True, "shutdown_verified": bool(miner_name), "reason": "Task engine and service ancestry verified"}


def _legacy_attribution(task: Optional[StartupTask], listener: Dict[str, Any], paths: InstallationPaths,
                        miner_name: Optional[str]) -> Dict[str, Any]:
    if not task or not task.owned or not task.enabled or not _task_identity_valid(asdict(task)):
        return {"verified": False, "reason": "Scheduled Task ownership or principal is unverified"}
    if ";" in task.action:
        return {"verified": False, "reason": "Scheduled Task has ambiguous launch actions"}
    match = re.search(r'-File\s+"([^"]+\.ps1)"|-File\s+([^\s;]+\.ps1)', task.action, re.IGNORECASE)
    if not match:
        return {"verified": False, "reason": "Scheduled Task launcher path is unavailable"}
    launcher = Path(match.group(1) or match.group(2))
    if not launcher.is_file():
        return {"verified": False, "reason": "Scheduled Task launcher is unavailable"}
    if task.name not in {TASK_NAMES["boot"], TASK_NAMES["logon"]}:
        return {"verified": False, "reason": "Scheduled Task name is not an owned coordinator task"}
    script = ("$ErrorActionPreference='Stop'; $s=New-Object -ComObject Schedule.Service; $s.Connect(); "
              f"$i=$s.GetFolder('\\').GetTask('{task.name}').GetInstances(0); "
              "@($i | ForEach-Object { [int]$_.EnginePID }) | ConvertTo-Json -Compress")
    try:
        result = subprocess.run([shutil.which("pwsh.exe") or "powershell.exe", "-NoProfile", "-NonInteractive",
                                 "-Command", script], capture_output=True, text=True, timeout=10, check=True)
        engines = json.loads(result.stdout or "[]")
        engines = engines if isinstance(engines, list) else [engines]
        if len(engines) != 1 or not engines[0]:
            return {"verified": False, "reason": "Scheduled Task must have exactly one running instance"}
        chain = []
        process = psutil.Process(int(listener["pid"]))
        for _ in range(8):
            snapshot = {"pid": process.pid, "ppid": process.ppid(), "create_time": process.create_time(),
                        "executable": process.exe(), "cmdline": process.cmdline()}
            chain.append(snapshot)
            if process.pid == engines[0]:
                break
            process = psutil.Process(snapshot["ppid"])
        engine_executable = chain[-1]["executable"]
        if not task.action.casefold().startswith((engine_executable + " ").casefold()):
            return {"verified": False, "reason": "Task engine executable differs from the registered action"}
        if launcher.stat().st_mtime > chain[-1]["create_time"]:
            return {"verified": False, "reason": "Launcher was modified after the task started"}
        verified = verify_legacy_evidence({"engine_pids": engines, "listener": listener, "chain": chain,
                                           "config": str(paths.config), "launcher": str(launcher)}, miner_name)
        if verified["verified"]:
            for item in chain:
                current = psutil.Process(item["pid"])
                if not _same_process_creation_time(current.create_time(), item["create_time"]) or current.ppid() != item["ppid"]:
                    return {"verified": False, "reason": "Process identity changed during attribution"}
            repeat = subprocess.run([shutil.which("pwsh.exe") or "powershell.exe", "-NoProfile", "-NonInteractive",
                                     "-Command", script], capture_output=True, text=True, timeout=10, check=True)
            repeat_engines = json.loads(repeat.stdout or "[]")
            if not isinstance(repeat_engines, list):
                repeat_engines = [repeat_engines]
            if repeat_engines != engines:
                return {"verified": False, "reason": "Scheduled Task instances changed during attribution"}
        return verified
    except (psutil.Error, OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return {"verified": False, "reason": "Task instance or process details are inaccessible; run the read-only preview with sufficient Windows privileges"}


def _exact_process_is_alive(pid: int, create_time: float) -> Optional[bool]:
    """Return None when identity cannot be checked; uncertainty is never treated as exit."""
    try:
        process = psutil.Process(pid)
        return abs(process.create_time() - float(create_time)) < 0.01
    except psutil.NoSuchProcess:
        return False
    except (psutil.AccessDenied, psutil.Error, OSError, TypeError, ValueError):
        return None


def _configured_executable_running(executable: str) -> Optional[bool]:
    """Conservatively detect an unmanaged copy of the configured executable."""
    expected_name = Path(executable).name.casefold()
    uncertain = False
    try:
        for process in psutil.process_iter(["name", "exe"]):
            try:
                name = str(process.info.get("name") or "").casefold()
                if name != expected_name:
                    continue
                return True
            except (psutil.AccessDenied, psutil.Error, OSError):
                uncertain = True
    except (psutil.AccessDenied, psutil.Error, OSError):
        return None
    return None if uncertain else False


def _effective_gpu_settings() -> Optional[Dict[str, Optional[float]]]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=power.limit,clocks.current.graphics,clocks.current.memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        row = next(csv.reader([result.stdout.strip()]))
        return {
            "power_limit_w": float(row[0].strip()),
            "graphics_clock_mhz": float(row[1].strip()),
            "memory_clock_mhz": float(row[2].strip()),
        }
    except (OSError, subprocess.SubprocessError, ValueError, IndexError, StopIteration):
        return None


def _task_identity_valid(task: Dict[str, Any]) -> bool:
    identity = str(task.get("user_id", "")).casefold().strip()
    mode = task.get("mode")
    if mode == "boot":
        return identity in {"system", "nt authority\\system", "s-1-5-18"}
    if mode != "logon":
        return False
    username = getpass.getuser().casefold()
    return identity == username or identity.endswith("\\" + username)


def render_launcher(paths: InstallationPaths) -> str:
    """Render the managed launcher while keeping all values as quoted literals."""
    modules = paths.repository / "modules"
    python_path = os.pathsep.join(
        str(modules / part) for part in ("resource_coordinator", "llm_monitor")
    )
    configured_state = ""
    if paths.config.is_file():
        configured_state = load_config(paths.config).service.state_persistence_path
    state_path = Path(configured_state).expanduser() if configured_state else paths.state
    miner_name = _configured_miner(paths.config) if paths.config.is_file() else None
    args = ["'-m'", "'resource_coordinator.cli'", "'serve'", "'-c'", _ps_single_quote(paths.config)]
    if miner_name:
        args.extend(["'--start-process'", _ps_single_quote(miner_name), "'--stop-process-on-shutdown'",
                     _ps_single_quote(miner_name)])
    else:
        args.append("'--first-boot'") if not paths.state.exists() else None
    return "\n".join(
        [
            "# " + TASK_MARKER,
            "$ErrorActionPreference = 'Stop'",
            f"$repoRoot = {_ps_single_quote(paths.repository)}",
            f"$python = {_ps_single_quote(paths.python)}",
            f"$config = {_ps_single_quote(paths.config)}",
            f"$state = {_ps_single_quote(state_path)}",
            f"$token = {_ps_single_quote(paths.token)}",
            f"$upgradePolicy = {_ps_single_quote(paths.upgrade_policy)}",
            f"$logDir = {_ps_single_quote(paths.logs)}",
            f"$log = {_ps_single_quote(paths.coordinator_log)}",
            "foreach ($path in @($config, $python)) { if (-not (Test-Path -LiteralPath $path)) { throw \"Required RC path missing: $path\" } }",
            "$probe = [System.Net.Sockets.TcpClient]::new()",
            "try { $connect = $probe.BeginConnect('127.0.0.1', 1235, $null, $null); if ($connect.AsyncWaitHandle.WaitOne(1000) -and $probe.Connected) { exit 0 } } finally { $probe.Dispose() }",
            f"$env:PYTHONPATH = {_ps_single_quote(python_path)}",
            "$env:RESOURCE_COORDINATOR_TOKEN_FILE = $token",
            "$env:RESOURCE_COORDINATOR_STATE_PATH = $state",
            "$env:RESOURCE_COORDINATOR_LOG_DIR = $logDir",
            "New-Item -ItemType Directory -Force -Path $logDir | Out-Null",
            "$serveArgs = @(" + ", ".join(args) + ")",
            "if (Test-Path -LiteralPath $upgradePolicy) {",
            "  $policy = Get-Content -LiteralPath $upgradePolicy -Raw | ConvertFrom-Json",
            "  Remove-Item -LiteralPath $upgradePolicy -Force",
            "  if (-not [bool]$policy.start_miner) {",
            "    $filtered = @(); for ($i=0; $i -lt $serveArgs.Count; $i++) { if ($serveArgs[$i] -eq '--start-process') { $i++; continue }; $filtered += $serveArgs[$i] }; $serveArgs = $filtered",
            "  }",
            "}",
            "if (-not (Test-Path -LiteralPath $state) -and $serveArgs -notcontains '--first-boot') { $serveArgs += '--first-boot' }",
            "Set-Location -LiteralPath $repoRoot",
            "& $python @serveArgs *>> $log",
            "exit $LASTEXITCODE",
            "",
        ]
    )


def render_viewer(paths: InstallationPaths) -> str:
    log_path = paths.logs / "krig_miner.log"
    if paths.config.is_file():
        config = load_config(paths.config)
        miner = next(
            (process for name, process in config.processes.items()
             if "miner" in name.casefold() or "krig" in name.casefold()),
            None,
        )
        if miner and miner.stdout_log_path:
            log_path = Path(miner.stdout_log_path)
    return "\n".join(
        [
            "# " + TASK_MARKER,
            "$ErrorActionPreference = 'Continue'",
            f"$logPath = {_ps_single_quote(log_path)}",
            "$offset = [int64]0",
            "$lastStatus = [datetime]::MinValue",
            "Write-Host 'KRig output viewer (read-only); close this window to hide it.' -ForegroundColor Cyan",
            "while ($true) {",
            "  if ((Get-Date) - $lastStatus -gt [timespan]::FromSeconds(3)) {",
            "    try { $s=Invoke-RestMethod -Uri 'http://127.0.0.1:1235/_coordinator/status' -TimeoutSec 2; $m=$s.processes.krig_miner; Write-Host ('[{0:HH:mm:ss}] coordinator={1} miner={2} PID={3} active={4} pending={5}' -f (Get-Date),$s.service_state,$m.state,$m.pid,$s.gpu_inference.active_count,$s.gpu_inference.pending_count) -ForegroundColor Green }",
            "    catch { Write-Host ('[{0:HH:mm:ss}] coordinator unavailable; retrying' -f (Get-Date)) -ForegroundColor Yellow }",
            "    $lastStatus = Get-Date",
            "  }",
            "  if (Test-Path -LiteralPath $logPath) {",
            "    try {",
            "      $fs=[IO.File]::Open($logPath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)",
            "      try { if ($fs.Length -lt $offset) { $offset=0 }; [void]$fs.Seek($offset,[IO.SeekOrigin]::Begin); $reader=[IO.StreamReader]::new($fs,[Text.Encoding]::UTF8,$true,1024,$true); $chunk=$reader.ReadToEnd(); $offset=$fs.Position; $reader.Dispose(); if ($chunk) { Write-Host -NoNewline $chunk } }",
            "      finally { $fs.Dispose() }",
            "    } catch { Write-Host ('Log temporarily unavailable: {0}' -f $_.Exception.Message) -ForegroundColor DarkYellow }",
            "  }",
            "  Start-Sleep -Milliseconds 500",
            "}",
            "",
        ]
    )
def classify_doctor(checks: Dict[str, Any]) -> Dict[str, Any]:
    """Classify collected facts without allowing an HTTP 200 to mask degraded operation."""
    warnings: List[str] = []
    blockers: List[str] = []
    if checks.get("service_ready") is not True:
        blockers.append("coordinator service is not ready")
    if checks.get("upgrade_in_progress") is True:
        blockers.append("an upgrade transition is in progress")
    if checks.get("upgrade_recovery_required") is True:
        blockers.append("upgrade recovery is required; inspect the persisted upgrade receipt")
    if (checks.get("runtime_source_matches") is not True or checks.get("runtime_version_matches") is not True
            or checks.get("runtime_revision_matches") is False):
        warnings.append("running coordinator source/version does not match the installed Resource Coordinator package")
    if checks.get("credential_ready") is not True:
        blockers.append("operator credential is unavailable or insecure")
    if checks.get("task_ready") is not True:
        warnings.append("no enabled RC startup task with the required identity and privilege was found")
    if checks.get("task_inventory_error"):
        warnings.append(f"Scheduled Task inventory is unavailable: {checks['task_inventory_error']}")
    configured = checks.get("configured_power_limit_w")
    effective = checks.get("effective_power_limit_w")
    if configured is not None and effective is not None and abs(float(configured) - float(effective)) > 0.5:
        warnings.append(f"effective GPU power limit {effective:g} W does not match configured {configured:g} W")
    configured_memory = checks.get("configured_gpu_settings", {}).get("memory_clock_mhz")
    observed_memory = (checks.get("gpu") or {}).get("memory_clock_mhz")
    if configured_memory is not None and observed_memory is not None and abs(float(configured_memory) - float(observed_memory)) > 100:
        warnings.append(
            f"observed GPU memory clock {observed_memory:g} MHz does not match configured "
            f"{configured_memory:g} MHz"
        )
    configured_gpu = checks.get("configured_gpu_settings", {})
    policy_verification = checks.get("gpu_policy_verification", {})
    for key, label in (("core_clock_mhz", "core clock lock"), ("core_offset_mhz", "core offset")):
        if key in configured_gpu and policy_verification.get(key) != "verified":
            warnings.append(f"configured GPU {label} is not independently verified by available driver telemetry")
    if checks.get("miner_expected") and checks.get("miner_owned") is not True:
        warnings.append("configured miner is not running under coordinator ownership")
    if checks.get("upstream_ready") is False:
        warnings.append("configured inference upstream is not responding")
    for name, log_check in checks.get("log_paths", {}).items():
        if log_check.get("parent_writable") is not True:
            warnings.append(f"process output capture path for '{name}' is not writable")
    return {
        "status": "blocked" if blockers else ("degraded" if warnings else "healthy"),
        "warnings": warnings,
        "blockers": blockers,
    }


class WindowsStartupTaskBackend:
    """Manage only the named RC tasks, using the built-in ScheduledTasks module."""

    def __init__(self, *, powershell: Optional[str] = None, managed_root: Optional[Path] = None,
                 interactive_user: Optional[str] = None):
        self.powershell = powershell or shutil.which("pwsh.exe") or shutil.which("powershell.exe") or "powershell.exe"
        self.managed_root = (managed_root or (Path.home() / ".resource_coordinator")).resolve()
        default_user = os.environ.get("USERDOMAIN", "")
        username = os.environ.get("USERNAME") or getpass.getuser()
        self.interactive_user = interactive_user or (f"{default_user}\\{username}" if default_user else username)

    @staticmethod
    def _admin() -> bool:
        if os.name != "nt":
            return False
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False

    def _script(self, payload: Dict[str, Any]) -> str:
        payload = {
            **payload,
            "managed_root": str(self.managed_root),
            "interactive_user": self.interactive_user,
        }
        payload_b64 = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
        return _TASKS_POWERSHELL.replace("__PAYLOAD__", payload_b64)

    def _run(self, payload: Dict[str, Any], *, elevated: bool = False,
             non_interactive: bool = False) -> subprocess.CompletedProcess[str]:
        if os.name != "nt":
            raise InstallationError("Windows Scheduled Tasks are available only on Windows")
        if elevated and not self._admin() and non_interactive:
            raise ElevationRequired("Administrator approval is required; rerun interactively or elevate PowerShell.")
        self.managed_root.mkdir(parents=True, exist_ok=True)
        if self.managed_root.is_symlink():
            raise InstallationError("Managed helper directory is a reparse point; refusing privileged execution")
        operation_id = os.urandom(16).hex()
        operation_dir = Path(tempfile.mkdtemp(prefix=f"operation-{operation_id}-", dir=self.managed_root))
        request_path, output_path, error_path = (operation_dir / name for name in ("request.json", "stdout.txt", "stderr.txt"))
        helper_path = operation_dir / "helper.ps1"
        result: Optional[subprocess.CompletedProcess[str]] = None
        try:
            root_acl = subprocess.run(["icacls.exe", str(self.managed_root), "/inheritance:r", "/grant:r",
                                       f"{self.interactive_user}:(OI)(CI)F", "SYSTEM:(OI)(CI)F",
                                       "Administrators:(OI)(CI)F"], capture_output=True, text=True, timeout=15)
            if root_acl.returncode:
                raise InstallationError("Could not restrict managed helper directory ACL")
            acl = subprocess.run(["icacls.exe", str(operation_dir), "/inheritance:r", "/grant:r",
                                  f"{self.interactive_user}:(OI)(CI)F", "SYSTEM:(OI)(CI)F",
                                  "Administrators:(OI)(CI)F"], capture_output=True, text=True, timeout=15)
            if acl.returncode:
                raise InstallationError("Could not restrict helper operation directory ACL: " + _clean_powershell_error(acl.stderr))
            body = _TASKS_POWERSHELL.replace(
                "$payload = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__PAYLOAD__')) | ConvertFrom-Json",
                "$payload = Get-Content -LiteralPath $RequestPath -Raw | ConvertFrom-Json",
            )
            request = {**payload, "managed_root": str(self.managed_root), "interactive_user": self.interactive_user,
                       "operation_id": operation_id, "result_path": str(output_path)}
            request_bytes = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            request_hash = hashlib.sha256(request_bytes).hexdigest()
            request_path.write_bytes(request_bytes)
            helper = ("param([Parameter(Mandatory)][string]$RequestPath)\n$ErrorActionPreference='Stop'\n"
                      f"$expectedOperation='{operation_id}'; $expectedHash='{request_hash}'\n"
                      "$actualHash=(Get-FileHash -LiteralPath $RequestPath -Algorithm SHA256).Hash.ToLowerInvariant()\n"
                      "if ($actualHash -ne $expectedHash) { throw 'Request integrity check failed.' }\n"
                      "$payload=Get-Content -LiteralPath $RequestPath -Raw | ConvertFrom-Json\n"
                      "if ([string]$payload.operation_id -ne $expectedOperation) { throw 'Operation ID mismatch.' }\n"
                      "$captured = & {\n" + body.split("\n", 1)[1] + "\n} 2>&1 | Out-String\n"
                      "$record=@{operation_id=[string]$payload.operation_id;request_sha256='" + request_hash +
                      "';state='completed';exit_code=0;output=$captured}\n"
                      "$tmp=[string]$payload.result_path+'.new'; $record | ConvertTo-Json -Depth 8 -Compress | "
                      "Set-Content -LiteralPath $tmp -Encoding utf8; Move-Item -LiteralPath $tmp -Destination "
                      "$payload.result_path -Force\n")
            helper_path.write_text(helper, encoding="utf-8")
            helper_hash = hashlib.sha256(helper_path.read_bytes()).hexdigest()
            if elevated and not self._admin():
                def ps_argument(value: Path) -> str:
                    return '"' + str(value).replace('"', '\\"') + '"'
                wrapper = (f"$p=Start-Process -FilePath {_ps_single_quote(self.powershell)} -Verb RunAs "
                           f"-WindowStyle Hidden -ArgumentList @('-NoProfile','-NonInteractive','-File',"
                           f"{_ps_single_quote(ps_argument(helper_path))},'-RequestPath',"
                           f"{_ps_single_quote(ps_argument(request_path))}) -Wait -PassThru; exit $p.ExitCode")
                result = subprocess.run([self.powershell, "-NoProfile", "-NonInteractive", "-Command", wrapper],
                                        capture_output=True, text=True, timeout=120)
            else:
                result = subprocess.run([self.powershell, "-NoProfile", "-NonInteractive", "-File",
                                         str(helper_path), "-RequestPath", str(request_path)],
                                        capture_output=True, text=True, timeout=120)
            if result.returncode:
                message = _clean_powershell_error(result.stderr or result.stdout)
                if "cancelled" in message.casefold() or "canceled" in message.casefold() or "0x800704c7" in message.casefold():
                    raise ElevationRequired("Administrator approval was cancelled; the existing service was not changed.")
                raise InstallationError(f"Task helper {operation_id} failed: {message or result.returncode}")
            if not output_path.is_file() or output_path.is_symlink():
                raise InstallationError(f"Task helper {operation_id} exited without a result record")
            record = json.loads(output_path.read_text(encoding="utf-8-sig"))
            if (record.get("operation_id") != operation_id or record.get("request_sha256") != request_hash
                    or record.get("state") != "completed" or record.get("exit_code") != 0):
                raise InstallationError(f"Task helper {operation_id} returned mismatched or incomplete evidence")
            if hashlib.sha256(helper_path.read_bytes()).hexdigest() != helper_hash:
                raise InstallationError(f"Task helper {operation_id} changed during execution")
            result.stdout = record.get("output", "")
        except subprocess.TimeoutExpired as exc:
            raise InstallationError(f"Task operation {operation_id} timed out; diagnostic artifacts retained at {operation_dir}") from exc
        finally:
            if operation_dir.exists() and result is not None and result.returncode == 0:
                shutil.rmtree(operation_dir, ignore_errors=True)
        if result.returncode:
            message = _clean_powershell_error(result.stderr or result.stdout) or f"PowerShell exited {result.returncode}"
            if "access is denied" in message.casefold() or "requires elevation" in message.casefold():
                raise ElevationRequired(f"Task operation {operation_id} requires elevation: {message}")
            raise InstallationError(f"Task operation {operation_id} failed; evidence retained at {operation_dir}: {message}")
        return result

    def status(self) -> List[StartupTask]:
        result = self._run({"operation": "status"})
        try:
            raw = json.loads(result.stdout or "[]")
            return [StartupTask(**task) for task in raw]
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            raise InstallationError("Scheduled Task status returned invalid data") from exc

    def snapshot(self, task: StartupTask) -> Dict[str, Any]:
        """Capture the exact owned task XML and enabled state before reconciliation."""
        if not task.owned or task.mode not in {"boot", "logon"}:
            raise InstallationError(f"Refusing to snapshot unowned coordinator task {task.name}")
        result = self._run({"operation": "snapshot", "task_name": task.name})
        try:
            snapshot = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            raise InstallationError("Scheduled Task snapshot returned invalid data") from exc
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("definition"), str):
            raise InstallationError("Scheduled Task snapshot is incomplete")
        return snapshot

    def restore_snapshot(self, task: StartupTask, snapshot: Dict[str, Any], *,
                         non_interactive: bool = False) -> None:
        """Restore a previously captured, RC-owned task definition."""
        if not task.owned or task.mode not in {"boot", "logon"}:
            raise InstallationError(f"Refusing to restore unowned coordinator task {task.name}")
        definition = snapshot.get("definition")
        enabled = snapshot.get("enabled")
        if not isinstance(definition, str) or type(enabled) is not bool:
            raise InstallationError("Scheduled Task recovery snapshot is invalid")
        self._run({"operation": "restore", "task_name": task.name,
                   "definition": definition, "enabled": enabled}, elevated=True,
                  non_interactive=non_interactive)

    def install(self, mode: str, launcher: Path, *, non_interactive: bool = False) -> StartupTask:
        if mode not in {"boot", "logon"}:
            raise InstallationError(f"Unsupported startup mode: {mode}")
        self._run({"operation": "install", "mode": mode, "launcher": str(launcher)}, elevated=True,
                  non_interactive=non_interactive)
        result = next((task for task in self.status() if task.name == TASK_NAMES[mode]), None)
        if result is None or not result.owned:
            raise InstallationError(f"Scheduled Task {TASK_NAMES[mode]} was not installed as an RC-owned task")
        return result

    def install_viewer(self, launcher: Path) -> StartupTask:
        self._run({"operation": "install_viewer", "launcher": str(launcher)})
        result = next((task for task in self.status() if task.name == TASK_NAMES["viewer"]), None)
        if result is None or not result.owned:
            raise InstallationError("Optional log viewer task was not installed as an RC-owned task")
        return result

    def set_enabled(self, task: StartupTask, enabled: bool, *, non_interactive: bool = False) -> StartupTask:
        if not task.owned:
            raise InstallationError(f"Refusing to change unowned Scheduled Task {task.name}")
        self._run(
            {"operation": "enable" if enabled else "disable", "task_name": task.name},
            elevated=task.mode != "viewer", non_interactive=non_interactive,
        )
        return next(item for item in self.status() if item.name == task.name)

    def uninstall(self, task: StartupTask, *, non_interactive: bool = False) -> None:
        if not task.owned:
            raise InstallationError(f"Refusing to remove unowned Scheduled Task {task.name}")
        self._run(
            {"operation": "uninstall", "task_name": task.name},
            elevated=task.mode != "viewer", non_interactive=non_interactive,
        )

    def start(self, task: StartupTask, *, non_interactive: bool = False) -> None:
        if not task.owned or not task.enabled:
            raise InstallationError(f"Refusing to start unowned or disabled Scheduled Task {task.name}")
        self._run({"operation": "start", "task_name": task.name}, elevated=True,
                  non_interactive=non_interactive)


class ManagedInstallation:
    def __init__(self, paths: InstallationPaths, task_backend: StartupTaskBackend,
                 *, template: Optional[Path] = None):
        self.paths = paths
        self.task_backend = task_backend
        self.template = template or paths.repository / "modules" / "resource_coordinator" / "config.production-template.yaml"

    def plan_setup(self, mode: str = "logon", *, viewer: bool = False) -> Dict[str, Any]:
        if mode not in {"boot", "logon"}:
            raise InstallationError(f"Unsupported startup mode: {mode}")
        plan = {
            "operation": "setup",
            "mode": mode,
            "changes": [
                {"resource": "managed_directories", "action": "create-if-missing", "path": str(self.paths.root)},
                {"resource": "configuration", "action": "preserve-or-copy-template", "path": str(self.paths.config)},
                {"resource": "operator_credential", "action": "load-or-create-securely", "path": str(self.paths.token)},
                {"resource": "launcher", "action": "write-managed-version", "path": str(self.paths.launcher)},
                {"resource": "startup_task", "action": "install-or-repair", "name": TASK_NAMES[mode]},
            ],
            "preserved": [str(self.paths.state), str(self.paths.logs)],
        }
        if viewer:
            plan["changes"].append(
                {"resource": "optional_log_viewer", "action": "install-at-user-logon", "path": str(self.paths.viewer)}
            )
        return plan

    @staticmethod
    def _write_managed(path: Path, content: str) -> bool:
        if path.exists() and TASK_MARKER not in path.read_text(encoding="utf-8", errors="replace"):
            raise InstallationError(f"Refusing to overwrite an unmarked user file: {path}")
        if path.exists() and path.read_text(encoding="utf-8") == content:
            return False
        temporary = path.with_name(path.name + ".new")
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
        return True

    def setup(self, *, apply: bool = False, mode: str = "logon", non_interactive: bool = False,
              activate: bool = True, viewer: bool = False) -> Dict[str, Any]:
        plan = self.plan_setup(mode, viewer=viewer)
        if not apply:
            return {"status": "planned", **plan}
        if not self.template.is_file() and not self.paths.config.is_file():
            raise InstallationError(f"Configuration template is missing: {self.template}")
        created: List[str] = []
        viewer_task: Optional[StartupTask] = None
        completed: List[str] = []
        stage = "creating managed directories"
        try:
            self.paths.root.mkdir(parents=True, exist_ok=True)
            self.paths.logs.mkdir(parents=True, exist_ok=True)
            self.paths.token.parent.mkdir(parents=True, exist_ok=True)
            completed.append("managed directories")
            stage = "validating configuration"
            if not self.paths.config.exists():
                shutil.copy2(self.template, self.paths.config)
                created.append("configuration")
            # Validation is read-only; existing comments and settings are preserved byte-for-byte.
            config = load_config(self.paths.config)
            completed.append("configuration")
            stage = "provisioning and checking the shared credential"
            load_or_create_token()
            credential = credential_doctor()
            if not (
                credential.get("credential_file_exists")
                and credential.get("credential_file_readable")
                and credential.get("credential_valid")
                and credential.get("acl_restricted") is True
                and credential.get("environment_override_matches_file") is not False
            ):
                raise InstallationError(
                    "The shared operator credential is not usable by the interactive user and SYSTEM. "
                    "Run 'resource-coordinator system auth doctor' and repair its ACL or explicitly reinitialize it."
                )
            completed.append("operator credential")
            stage = "writing the managed launcher"
            if self._write_managed(self.paths.launcher, render_launcher(self.paths)):
                created.append("launcher")
            completed.append("launcher")
            stage = "installing and enabling the startup task"
            task = self.task_backend.install(mode, self.paths.launcher, non_interactive=non_interactive)
            task = self.task_backend.set_enabled(task, True, non_interactive=non_interactive)
            completed.append("startup task")
            if viewer:
                stage = "writing the optional log viewer"
                if self._write_managed(self.paths.viewer, render_viewer(self.paths)):
                    created.append("viewer")
                completed.append("viewer script")
                stage = "installing the optional log viewer task"
                viewer_task = self.task_backend.install_viewer(self.paths.viewer)
                viewer_task = self.task_backend.set_enabled(viewer_task, True, non_interactive=non_interactive)
                completed.append("viewer task")
            activation = "not-started-by-startup-command" if not activate else "already-running"
            if activate:
                stage = "starting and checking the coordinator"
                service = self._service_status()
                if service is None:
                    self.task_backend.start(task, non_interactive=non_interactive)
                    service = self._wait_for_service()
                    activation = "started" if service else "starting"
                elif service.get("service_state") == "ready":
                    try:
                        with httpx.Client(timeout=2.0) as client:
                            route = client.get(f"{COORDINATOR_URL}/_coordinator/miner/status")
                        if route.status_code != 200:
                            activation = "running-older-api"
                    except httpx.HTTPError:
                        activation = "running-api-unverified"
        except Exception as exc:
            finished = ", ".join(completed) if completed else "none"
            raise InstallationError(
                f"Setup failed while {stage}; completed resources: {finished}. "
                f"No credential values were displayed. Correct the issue and rerun setup --apply. Details: {exc}"
            ) from exc
        miner_name = _configured_miner(self.paths.config)
        has_miner_process = any(
            "miner" in name.casefold() or "krig" in name.casefold() for name in config.processes
        )
        mining_warning = None
        if not has_miner_process:
            mining_warning = "No miner process is configured; mining will not start until configuration is supplied."
        elif miner_name is None:
            mining_warning = "Miner account is still a placeholder; mining will not start until it is configured."
        successful_activation = activation in {
            "already-running", "started", "not-started-by-startup-command"
        }
        service_for_upgrade = self._service_status() if activate else None
        expected_runtime = build_runtime_identity(self.paths.repository / "modules" / "resource_coordinator" /
                                                  "resource_coordinator")
        reported_runtime = (service_for_upgrade or {}).get("runtime") or {}
        upgrade_available = bool(
            service_for_upgrade and service_for_upgrade.get("service_state") == "ready" and
            (reported_runtime.get("revision") != expected_runtime["revision"] or
             reported_runtime.get("version") != expected_runtime["version"] or
             not _runtime_source_matches(reported_runtime.get("source_path"),
                                        Path(expected_runtime["source_path"])))
        )
        return {
            "status": "applied" if successful_activation and mining_warning is None else "degraded",
            "created": created,
            "task": asdict(task),
            "viewer_task": asdict(viewer_task) if viewer_task else None,
            "config_path": str(self.paths.config),
            "processes_configured": sorted(config.processes),
            "miner_identity_configured": miner_name is not None,
            "mining_warning": mining_warning,
            "service_activation": activation,
            "runtime_upgrade_available": upgrade_available,
            "recommendation": "Run 'resource-coordinator system upgrade --apply' to activate the current source."
            if upgrade_available else None,
            "preserved": [str(self.paths.state), str(self.paths.logs)],
        }

    def startup_status(self) -> Dict[str, Any]:
        tasks = self.task_backend.status()
        return {"tasks": [asdict(task) for task in tasks],
                "authoritative": next((task.name for task in tasks if task.owned and task.enabled and task.mode in {"boot", "logon"}), None)}

    def plan_teardown(self) -> Dict[str, Any]:
        return {
            "status": "planned",
            "operation": "teardown",
            "targets": [str(self.paths.launcher), "RC-owned startup tasks"],
            "preserved": [str(self.paths.config), str(self.paths.token), str(self.paths.state), str(self.paths.logs)],
        }

    def startup(self, action: str, *, apply: bool = False, mode: Optional[str] = None,
                non_interactive: bool = False) -> Dict[str, Any]:
        if action == "status":
            return self.startup_status()
        current = self.task_backend.status()
        owned = [task for task in current if task.owned and task.mode in {"boot", "logon"}]
        if action in {"install", "repair"}:
            selected_mode = mode or next((task.mode for task in owned if task.enabled), "logon")
            if not apply:
                return {"status": "planned", "operation": action, "mode": selected_mode,
                        "task": TASK_NAMES[selected_mode], "preserves_running_service": True}
            return self.setup(apply=True, mode=selected_mode, non_interactive=non_interactive,
                              activate=False)
        if action not in {"enable", "disable", "uninstall"}:
            raise InstallationError(f"Unsupported startup operation: {action}")
        if not apply:
            return {"status": "planned", "operation": action, "tasks": [task.name for task in owned],
                    "running_coordinator_affected": False}
        if action == "uninstall":
            for task in owned:
                self.task_backend.uninstall(task, non_interactive=non_interactive)
            return {"status": "applied", "tasks_uninstalled": [task.name for task in owned],
                    "running_coordinator_affected": False}
        enabled = action == "enable"
        if enabled and not owned:
            raise InstallationError("No RC startup task is installed; use 'startup install -m logon -a' first.")
        selected = owned if not enabled else [next((task for task in owned if task.enabled), owned[0])]
        updated = [self.task_backend.set_enabled(task, enabled, non_interactive=non_interactive) for task in selected]
        return {"status": "applied", "operation": action, "tasks": [asdict(task) for task in updated],
                "running_coordinator_affected": False}

    def _upgrade_preflight(self, *, non_interactive: bool = False) -> Dict[str, Any]:
        """Read-only upgrade inspection. Every unknown ownership fact is a blocker."""
        source_identity = build_runtime_identity(self.paths.repository / "modules" / "resource_coordinator" /
                                                 "resource_coordinator")
        service = self._service_status()
        tasks = self.task_backend.status()
        enabled = [task for task in tasks if task.owned and task.enabled and task.mode in {"boot", "logon"}]
        blockers: List[str] = []
        if not self.paths.python.is_file():
            blockers.append(f"configured Python executable is missing: {self.paths.python}")
        source_package = self.paths.repository / "modules" / "resource_coordinator" / "resource_coordinator" / "__init__.py"
        if not source_package.is_file():
            blockers.append(f"current Resource Coordinator source package is missing: {source_package}")
        try:
            rendered_launcher = render_launcher(self.paths)
            if TASK_MARKER not in rendered_launcher or str(self.paths.config) not in rendered_launcher:
                raise ValueError("managed launcher did not contain expected ownership/configuration markers")
        except Exception as exc:
            blockers.append(f"managed launcher cannot be rendered and validated: {exc}")
        if service is None:
            blockers.append("coordinator status is unavailable; upgrade will not start a replacement owner")
        elif service.get("service_state") != "ready":
            blockers.append(f"coordinator is not ready ({service.get('service_state')})")
        if len(enabled) != 1:
            blockers.append(f"expected exactly one enabled RC startup task, found {len(enabled)}")
        task = enabled[0] if len(enabled) == 1 else None
        is_admin = getattr(self.task_backend, "_admin", lambda: True)()
        if non_interactive and not is_admin:
            blockers.append("startup task update requires administrator approval, but non-interactive mode forbids UAC")
        if task and (task.run_level != "Highest" or not _task_identity_valid(asdict(task))):
            blockers.append(f"startup task {task.name} has an unexpected identity or privilege level")

        runtime = (service or {}).get("runtime") or {}
        listener_details = _listener_identity_details()
        listener = listener_details.get("identity") if listener_details.get("verified") else None
        runtime_pid = runtime.get("pid")
        runtime_create_time = runtime.get("process_create_time")
        if listener is None:
            blockers.append(_listener_failure_reason(listener_details, "127.0.0.1", 1235))
        elif runtime_pid is not None and runtime_pid != listener.get("pid"):
            blockers.append("HTTP runtime PID does not match the process owning port 1235")
        legacy_needed = listener is not None and (runtime_pid is None or not runtime.get("revision"))
        if listener and runtime_create_time is not None and not _same_process_creation_time(
                runtime_create_time, listener["create_time"]):
            blockers.append("HTTP runtime creation time does not match the process owning port 1235")

        config = None
        journal = None
        miner_name = None
        try:
            config = load_config(self.paths.config)
            state_path = Path(config.service.state_persistence_path).expanduser()
            if not config.service.state_persistence_path or not state_path.is_file():
                raise ValueError("durable state journal is missing")
            journal = StateCodec.load(state_path)
            miner_name = _configured_miner(self.paths.config)
        except Exception as exc:
            blockers.append(f"configuration or durable journal cannot be verified: {exc}")

        if legacy_needed:
            attribution = _legacy_attribution(task, listener, self.paths, miner_name)
            runtime = {**runtime, "legacy_attribution": attribution}
            if not attribution.get("verified"):
                blockers.append("Legacy task attribution blocked: " + attribution.get("reason", "identity unavailable"))
            else:
                runtime = {**runtime, "pid": listener["pid"], "legacy_identity": True,
                           "legacy_task_identity_verified": True,
                           "shutdown_miner_verified_from_launcher": attribution.get("shutdown_verified", False)}

        if journal and journal.gaming_mode.get("state", "inactive") != "inactive":
            blockers.append(f"gaming transition is {journal.gaming_mode.get('state')}; finish it before upgrade")
        gpu_status = (service or {}).get("gpu_inference", {})
        if gpu_status.get("is_restart_inhibited"):
            blockers.append("inference restart is inhibited; resolve the safety inhibition before upgrade")
        if service and (gpu_status.get("active_count") is None or gpu_status.get("pending_count") is None):
            blockers.append("service does not report complete active/pending inference counts")

        processes = (service or {}).get("processes", {})
        miner = processes.get(miner_name, {}) if miner_name else {}
        miner_state = miner.get("state")
        miner_running = miner_state == "running"
        if miner_name and miner_state not in {"running", "stopped"}:
            blockers.append(f"configured miner state is unavailable or transitional ({miner_state or 'unknown'})")
        if miner_running and (not miner.get("is_coordinator_owned") or not miner.get("pid") or
                              miner.get("create_time") is None):
            blockers.append("running miner ownership or exact process identity is uncertain")
        shutdown_check = "verified" if (runtime.get("stop_miner_on_shutdown") or
                                         runtime.get("shutdown_miner_verified_from_launcher")) else "not-evaluated"
        if miner_running and shutdown_check != "verified" and not legacy_needed:
            shutdown_check = "unverified"
            blockers.append("running service does not confirm stop-miner-on-shutdown; refusing to risk an orphan")

        if journal:
            uncertain_requests = [
                request.request_id for request in journal.requests.values()
                if request.phase in {RequestPhase.POSSIBLY_FORWARDED, RequestPhase.UNCERTAIN}
            ]
            if uncertain_requests:
                blockers.append(
                    f"durable journal contains uncertain inferences ({len(uncertain_requests)}); resolve recovery first"
                )

        credential_ok = False
        try:
            load_token()
            credential = credential_doctor()
            credential_ok = bool(credential.get("credential_valid") and credential.get("credential_file_readable")
                                 and credential.get("acl_restricted") is True
                                 and credential.get("environment_override_matches_file") is not False)
        except Exception:
            credential_ok = False
        if not credential_ok:
            blockers.append("operator credential cannot be safely loaded by this CLI")

        snapshot = None
        if task:
            snapshotter = getattr(self.task_backend, "snapshot", None)
            if not callable(snapshotter):
                blockers.append("startup backend cannot snapshot the exact task definition for recovery")
            else:
                try:
                    snapshot = snapshotter(task)
                except Exception as exc:
                    blockers.append(f"startup task recovery snapshot failed: {exc}")

        configured_gpu = _configured_gpu_settings(config) if config else {}
        persisted_miner = journal.processes.get(miner_name) if journal and miner_name else None
        miner_resume_allowed = bool(
            miner_running and not (persisted_miner and persisted_miner.is_manual_override)
        )
        managed_launcher = bool(task and os.path.normcase(str(self.paths.launcher)) in
                                os.path.normcase(task.action))
        runtime_current = bool(
            runtime.get("revision") == source_identity["revision"] and
            runtime.get("version") == source_identity["version"] and managed_launcher and
            _runtime_source_matches(runtime.get("source_path"), Path(source_identity["source_path"]))
        )
        return {
            "source": source_identity,
            "runtime": runtime,
            "runtime_legacy": not bool(runtime.get("revision")),
            "managed_launcher_current": managed_launcher,
            "runtime_current": runtime_current,
            "service": service,
            "listener": listener,
            "listener_discovery": listener_details,
            "miner_shutdown_check": shutdown_check,
            "task": asdict(task) if task else None,
            "task_snapshot": snapshot,
            "miner_name": miner_name,
            "miner": miner,
            "miner_was_running": miner_running,
            "miner_resume_allowed": miner_resume_allowed,
            "miner_manual_hold": bool(persisted_miner and persisted_miner.is_manual_override),
            "journal": journal.to_dict() if journal else None,
            "gaming_state": journal.gaming_mode.get("state", "inactive") if journal else "unknown",
            "configured_gpu_settings": configured_gpu,
            "configured_upstream_url": config.service.upstream_url if config else None,
            "elevation_required": not is_admin,
            "elevation_mode": "non-interactive-blocked" if non_interactive and not is_admin else
                              "uac-required" if not is_admin else "already-elevated",
            "effective_gpu_settings": _effective_gpu_settings(),
            "blockers": blockers,
        }

    def _resume_interrupted_upgrade(self, preflight: Dict[str, Any], *,
                                    non_interactive: bool, timeout: float) -> Optional[Dict[str, Any]]:
        """Retry only a receipt-backed transition whose old owner is proven gone."""
        try:
            receipt = json.loads(self.paths.upgrade_receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if receipt.get("phase") not in {
            "PREPARED", "DRAINING", "OLD_STOPPED", "TASK_UPDATED", "RECOVERY_REQUIRED"
        }:
            return None
        if receipt.get("source", {}).get("revision") != preflight["source"].get("revision"):
            return {"status": "blocked", "phase": "RECOVERY_REQUIRED",
                    "blockers": ["source changed since the interrupted upgrade; inspect the receipt before retrying"]}
        expected_absent = {"coordinator status is unavailable; upgrade will not start a replacement owner"}
        blockers = list(preflight["blockers"])
        listener_details = preflight.get("listener_discovery") or {}
        if listener_details.get("category") == "not-found":
            blockers = [item for item in blockers if not item.startswith("No listening endpoint matching 127.0.0.1:1235")]
        unknown_miner = next((item for item in blockers if item.startswith("configured miner state is unavailable")), None)
        if unknown_miner and preflight.get("miner_name"):
            miner_config = load_config(self.paths.config).processes[preflight["miner_name"]]
            executable_running = _configured_executable_running(miner_config.executable)
            if executable_running is False:
                blockers.remove(unknown_miner)
            else:
                return {"status": "blocked", "phase": "RECOVERY_REQUIRED",
                        "blockers": ["offline miner process identity is uncertain" if executable_running is None else
                                     "a configured miner process is still running"]}
        if set(blockers) - expected_absent:
            return {"status": "blocked", "phase": "RECOVERY_REQUIRED", "blockers": blockers}
        if self._coordinator_port_open() or _listener_identity() is not None:
            return {"status": "blocked", "phase": "RECOVERY_REQUIRED",
                    "blockers": ["a coordinator listener exists; recovery will not start another owner"]}
        old_pid = receipt.get("old_service_pid")
        old_created = receipt.get("old_service_create_time")
        if type(old_pid) is not int or type(old_created) not in (int, float):
            return {"status": "blocked", "phase": "RECOVERY_REQUIRED",
                    "blockers": ["receipt lacks the old coordinator's exact process identity"]}
        if _exact_process_is_alive(old_pid, float(old_created)) is not False:
            return {"status": "blocked", "phase": "RECOVERY_REQUIRED",
                    "blockers": ["old coordinator process has not been proven exited"]}
        old_miner = receipt.get("old_miner") or {}
        if receipt.get("miner_was_running"):
            pid, created = old_miner.get("pid"), old_miner.get("create_time")
            if type(pid) is not int or type(created) not in (int, float):
                return {"status": "blocked", "phase": "RECOVERY_REQUIRED",
                        "blockers": ["receipt lacks the prior miner's exact process identity"]}
            if _exact_process_is_alive(pid, float(created)) is not False:
                return {"status": "blocked", "phase": "RECOVERY_REQUIRED",
                        "blockers": ["prior miner process has not been proven exited"]}
        config = load_config(self.paths.config)
        lock_path = Path(config.service.state_persistence_path).with_suffix(".lock")
        probe = SingleInstanceLock(lock_path)
        if not probe.acquire():
            return {"status": "blocked", "phase": "RECOVERY_REQUIRED",
                    "blockers": ["coordinator instance lock is still held or inaccessible"]}
        probe.release()

        tasks = [task for task in self.task_backend.status()
                 if task.owned and task.enabled and task.mode in {"boot", "logon"}]
        if len(tasks) != 1:
            return {"status": "blocked", "phase": "RECOVERY_REQUIRED",
                    "blockers": [f"recovery requires exactly one enabled owned task; found {len(tasks)}"]}
        task = tasks[0]
        if task.run_level != "Highest" or not _task_identity_valid(asdict(task)):
            return {"status": "blocked", "phase": "RECOVERY_REQUIRED",
                    "blockers": ["startup task identity or privilege level is not verified"]}
        token = load_token()
        if not credential_doctor().get("acl_restricted"):
            return {"status": "blocked", "phase": "RECOVERY_REQUIRED",
                    "blockers": ["operator credential ACL is not verified"]}
        if not self.paths.launcher.is_file():
            self._write_managed(self.paths.launcher, render_launcher(self.paths))
        if os.path.normcase(str(self.paths.launcher)) not in os.path.normcase(task.action):
            snapshot = receipt.get("task_snapshot")
            if not isinstance(snapshot, dict):
                return {"status": "blocked", "phase": "RECOVERY_REQUIRED",
                        "blockers": ["receipt has no exact task definition for safe recovery"]}
            task = self.task_backend.install(task.mode, self.paths.launcher, non_interactive=non_interactive)
            receipt["task_after"] = asdict(task)
        _write_json_atomic(self.paths.upgrade_policy, {"start_miner": False})
        receipt.update(phase="TASK_UPDATED", updated_at=time.time(), retry_count=int(receipt.get("retry_count", 0)) + 1)
        _write_json_atomic(self.paths.upgrade_receipt, receipt)
        self.task_backend.start(task, non_interactive=non_interactive)
        service = self._wait_for_service(timeout=timeout)
        if not service:
            receipt.update(phase="RECOVERY_REQUIRED", failed_at="TASK_UPDATED",
                           error="retry task did not produce a ready service", updated_at=time.time())
            _write_json_atomic(self.paths.upgrade_receipt, receipt)
            return {"status": "recovery-required", "phase": "TASK_UPDATED",
                    "blocker": "Retry started the owned task, but readiness was not verified.",
                    "receipt": str(self.paths.upgrade_receipt)}
        runtime = service.get("runtime") or {}
        listener = _listener_identity()
        if (runtime.get("revision") != preflight["source"]["revision"] or
                service.get("upstream_url") != preflight.get("configured_upstream_url") or listener is None or
                listener.get("pid") != runtime.get("pid") or
                not _runtime_source_matches(runtime.get("source_path"), Path(preflight["source"]["source_path"]))):
            receipt.update(phase="RECOVERY_REQUIRED", failed_at="NEW_READY",
                           error="runtime fingerprint/listener verification failed", updated_at=time.time())
            _write_json_atomic(self.paths.upgrade_receipt, receipt)
            return {"status": "recovery-required", "phase": "NEW_READY",
                    "blocker": "Retry service identity could not be verified; mining remains held.",
                    "receipt": str(self.paths.upgrade_receipt)}
        created = runtime.get("process_create_time")
        if created is None or not _same_process_creation_time(created, listener["create_time"]):
            receipt.update(phase="RECOVERY_REQUIRED", failed_at="NEW_READY",
                           error="runtime process creation time does not match the listener", updated_at=time.time())
            _write_json_atomic(self.paths.upgrade_receipt, receipt)
            return {"status": "recovery-required", "phase": "NEW_READY",
                    "blocker": "Retry runtime creation time could not be matched to its OS listener; mining remains held.",
                    "receipt": str(self.paths.upgrade_receipt)}
        with httpx.Client(timeout=5.0) as client:
            control = client.get(f"{COORDINATOR_URL}/_coordinator/miner/status")
        if control.status_code != 200:
            return {"status": "recovery-required", "phase": "NEW_READY", "runtime": runtime,
                    "blocker": f"Recovered coordinator miner-control API is unavailable ({control.status_code}).",
                    "receipt": str(self.paths.upgrade_receipt)}
        effective = _effective_gpu_settings()
        expected_power = (receipt.get("configured_gpu_settings") or {}).get("power_limit_w")
        if receipt.get("miner_resume_allowed") and expected_power is not None and (
                effective is None or effective.get("power_limit_w") is None or
                abs(float(effective["power_limit_w"]) - float(expected_power)) > 0.5):
            receipt.update(phase="RECOVERY_REQUIRED", failed_at="NEW_READY",
                           error="effective GPU power limit does not match configured policy", updated_at=time.time())
            _write_json_atomic(self.paths.upgrade_receipt, receipt)
            return {"status": "recovery-required", "phase": "NEW_READY", "runtime": runtime,
                    "effective_gpu_settings": effective,
                    "blocker": "Coordinator is ready; prior mining remains stopped because GPU policy failed.",
                    "receipt": str(self.paths.upgrade_receipt)}
        if receipt.get("miner_resume_allowed"):
            response = httpx.post(
                f"{COORDINATOR_URL}/_coordinator/miner/resume",
                headers={"Authorization": f"Bearer {token}"},
                json={"operator": getpass.getuser(), "reason": "Restore prior miner state after upgrade recovery"},
                timeout=10.0,
            )
            if response.status_code != 200:
                return {"status": "recovery-required", "phase": "NEW_READY", "runtime": runtime,
                        "blocker": f"Recovered coordinator refused safe miner resume ({response.status_code}).",
                        "receipt": str(self.paths.upgrade_receipt)}
            service = self._wait_for_service(timeout=10.0) or service
            miner_after = (service.get("processes") or {}).get(receipt.get("old_miner", {}).get("name"), {})
            if miner_after.get("state") != "running" or not miner_after.get("is_coordinator_owned"):
                return {"status": "recovery-required", "phase": "NEW_READY", "runtime": runtime,
                        "blocker": "Recovered coordinator did not verify ownership of the resumed miner.",
                        "receipt": str(self.paths.upgrade_receipt)}
        elif preflight.get("miner_name"):
            miner_after = (service.get("processes") or {}).get(preflight["miner_name"], {})
            if miner_after.get("state") != "stopped":
                receipt.update(phase="RECOVERY_REQUIRED", failed_at="NEW_READY",
                               error="miner was not verified stopped under the persisted hold", updated_at=time.time())
                _write_json_atomic(self.paths.upgrade_receipt, receipt)
                return {"status": "recovery-required", "phase": "NEW_READY", "runtime": runtime,
                        "blocker": "Persisted mining hold is active, but the recovered service did not verify mining stayed stopped.",
                        "receipt": str(self.paths.upgrade_receipt)}
        receipt.update(phase="VERIFIED", new_runtime=runtime, effective_gpu_settings_after=effective,
                       updated_at=time.time())
        _write_json_atomic(self.paths.upgrade_receipt, receipt)
        return {"status": "verified", "phase": "VERIFIED", "runtime": runtime,
                "recovered": True, "effective_gpu_settings": effective,
                "receipt": str(self.paths.upgrade_receipt)}

    def _finalize_ready_upgrade(self, preflight: Dict[str, Any]) -> Dict[str, Any]:
        """Complete a verified new runtime after a prior GPU-policy recovery hold."""
        try:
            receipt = json.loads(self.paths.upgrade_receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"status": "blocked", "phase": "RECOVERY_REQUIRED", "blockers": [str(exc)]}
        service = preflight.get("service") or {}
        if (receipt.get("phase") != "RECOVERY_REQUIRED" or receipt.get("failed_at") != "NEW_READY" or
                service.get("service_state") != "ready" or not preflight.get("runtime_current") or
                service.get("upstream_url") != preflight.get("configured_upstream_url")):
            return {"status": "blocked", "phase": "RECOVERY_REQUIRED",
                    "blockers": ["receipt and ready runtime do not describe the same verified upgrade"]}
        gpu = service.get("gpu_inference") or {}
        if gpu.get("active_count") != 0 or gpu.get("pending_count") != 0 or gpu.get("is_restart_inhibited"):
            return {"status": "recovery-required", "phase": "NEW_READY",
                    "blocker": "inference is active, pending, or inhibited; leave mining held and retry later"}
        with httpx.Client(timeout=5.0) as client:
            control = client.get(f"{COORDINATOR_URL}/_coordinator/miner/status")
        if control.status_code != 200:
            return {"status": "recovery-required", "phase": "NEW_READY",
                    "blocker": f"miner-control API is unavailable ({control.status_code})"}
        effective = _effective_gpu_settings()
        expected_power = (receipt.get("configured_gpu_settings") or {}).get("power_limit_w")
        if expected_power is not None and (
                effective is None or effective.get("power_limit_w") is None or
                abs(float(effective["power_limit_w"]) - float(expected_power)) > 0.5):
            return {"status": "recovery-required", "phase": "NEW_READY", "effective_gpu_settings": effective,
                    "blocker": "effective GPU power policy still does not match configuration"}
        miner_name = preflight.get("miner_name")
        miner = (service.get("processes") or {}).get(miner_name, {}) if miner_name else {}
        if receipt.get("miner_resume_allowed") and preflight.get("miner_manual_hold"):
            return {"status": "recovery-required", "phase": "NEW_READY",
                    "blocker": "a newer persisted manual mining hold takes precedence over the saved pre-upgrade state"}
        if receipt.get("miner_resume_allowed"):
            if miner.get("state") != "running":
                token = load_token()
                response = httpx.post(
                    f"{COORDINATOR_URL}/_coordinator/miner/resume",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"operator": getpass.getuser(), "reason": "Resume prior mining after GPU policy recovery"},
                    timeout=10.0,
                )
                if response.status_code != 200:
                    return {"status": "recovery-required", "phase": "NEW_READY",
                            "blocker": f"safe miner resume was rejected ({response.status_code})"}
                service = self._service_status() or service
                miner = (service.get("processes") or {}).get(miner_name, {})
            if miner.get("state") != "running" or not miner.get("is_coordinator_owned"):
                return {"status": "recovery-required", "phase": "NEW_READY",
                        "blocker": "prior mining state is not running under coordinator ownership"}
        elif miner.get("state") == "running":
            return {"status": "recovery-required", "phase": "NEW_READY",
                    "blocker": "miner is running despite a prior stopped/held state; manual reconciliation is required"}
        receipt.update(phase="VERIFIED", new_runtime=service.get("runtime"),
                       effective_gpu_settings_after=effective, updated_at=time.time())
        _write_json_atomic(self.paths.upgrade_receipt, receipt)
        return {"status": "verified", "phase": "VERIFIED", "runtime": service.get("runtime"),
                "recovered": True, "effective_gpu_settings": effective,
                "receipt": str(self.paths.upgrade_receipt)}

    def upgrade(self, *, apply: bool = False, non_interactive: bool = False,
                timeout: float = 45.0) -> Dict[str, Any]:
        if not apply:
            return self._upgrade_impl(apply=False, non_interactive=non_interactive, timeout=timeout)
        preflight = self._upgrade_preflight(non_interactive=non_interactive)
        if preflight["runtime_current"]:
            if self.paths.upgrade_receipt.is_file():
                try:
                    receipt = json.loads(self.paths.upgrade_receipt.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    receipt = {}
                if receipt.get("phase") == "RECOVERY_REQUIRED" and receipt.get("failed_at") == "NEW_READY":
                    lock = SingleInstanceLock(self.paths.upgrade_receipt.with_suffix(".lock"))
                    if not lock.acquire():
                        return {"status": "blocked", "phase": "RECOVERY_REQUIRED",
                                "blockers": ["another Resource Coordinator upgrade holds the upgrade lock"]}
                    try:
                        return self._finalize_ready_upgrade(preflight)
                    finally:
                        lock.release()
            return {"status": "already-current", "phase": "VERIFIED", "preflight": preflight}
        recoverable_offline = preflight["service"] is None and self.paths.upgrade_receipt.is_file()
        if preflight["blockers"] and not recoverable_offline:
            return {"status": "blocked", "phase": "PREFLIGHT", "preflight": preflight}
        lock = SingleInstanceLock(self.paths.upgrade_receipt.with_suffix(".lock"))
        if not lock.acquire():
            return {"status": "blocked", "phase": "PREFLIGHT",
                    "blockers": ["another Resource Coordinator upgrade already holds the upgrade lock"]}
        try:
            return self._upgrade_impl(apply=True, non_interactive=non_interactive, timeout=timeout,
                                      preflight=preflight)
        finally:
            lock.release()

    def _upgrade_impl(self, *, apply: bool, non_interactive: bool, timeout: float,
                      preflight: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Orchestrate an external, receipt-backed service upgrade without hot reload."""
        preflight = preflight or self._upgrade_preflight(non_interactive=non_interactive)
        if apply and preflight["service"] is None and self.paths.upgrade_receipt.is_file():
            recovered = self._resume_interrupted_upgrade(
                preflight, non_interactive=non_interactive, timeout=timeout
            )
            if recovered is not None:
                return recovered
        if preflight["runtime_current"]:
            return {"status": "already-current", "phase": "VERIFIED", "preflight": preflight}
        if preflight["blockers"]:
            return {"status": "blocked", "phase": "PREFLIGHT", "preflight": preflight}
        plan = {
            "status": "planned",
            "phase": "PREFLIGHT",
            "source_version": preflight["source"].get("version"),
            "source_revision": preflight["source"]["revision"],
            "runtime_version": preflight["runtime"].get("version"),
            "runtime_revision": preflight["runtime"].get("revision"),
            "runtime_legacy": preflight["runtime_legacy"],
            "startup_task": preflight["task"]["name"],
            "elevation_required": preflight["elevation_required"],
            "elevation_mode": preflight["elevation_mode"],
            "miner_was_running": preflight["miner_was_running"],
            "miner_resume_allowed": preflight["miner_resume_allowed"],
            "configured_gpu_settings": preflight["configured_gpu_settings"],
            "effective_gpu_settings": preflight["effective_gpu_settings"],
            "configured_upstream_url": preflight["configured_upstream_url"],
            "will_drain_inference": True,
            "changes": ["gracefully stop current coordinator and owned miner", "reconcile RC startup task",
                        "start one coordinator and verify runtime identity"],
        }
        if not apply:
            return plan

        assert preflight["task"] is not None
        task = StartupTask(**preflight["task"])
        original_launcher_text = self.paths.launcher.read_text(encoding="utf-8") if self.paths.launcher.exists() else None
        receipt = {
            "schema": 1,
            "phase": "PREPARED",
            "source": preflight["source"],
            "old_runtime": preflight["runtime"],
            "old_service_pid": preflight["listener"]["pid"],
            "old_service_create_time": preflight["listener"]["create_time"],
            "old_miner": preflight["miner"],
            "miner_was_running": preflight["miner_was_running"],
            "miner_resume_allowed": preflight["miner_resume_allowed"],
            "durable_state": preflight["journal"],
            "configured_gpu_settings": preflight["configured_gpu_settings"],
            "configured_upstream_url": preflight["configured_upstream_url"],
            "effective_gpu_settings_before": preflight["effective_gpu_settings"],
            "task": preflight["task"],
            "task_snapshot": preflight["task_snapshot"],
            "elevation_mode": preflight["elevation_mode"],
            "launcher_existed": original_launcher_text is not None,
        }
        if original_launcher_text is not None:
            receipt["launcher_backup"] = original_launcher_text
        _write_json_atomic(self.paths.upgrade_receipt, receipt)

        def update_phase(phase: str, **extra: Any) -> None:
            receipt.update(phase=phase, updated_at=time.time(), **extra)
            _write_json_atomic(self.paths.upgrade_receipt, receipt)

        task_updated = False
        task_update_started = False
        try:
            self._write_managed(self.paths.launcher, render_launcher(self.paths))
            # The task launch is held from auto-starting mining until this external
            # process verifies the new runtime and GPU policy.
            _write_json_atomic(self.paths.upgrade_policy, {"start_miner": False})
            update_phase("PREPARED", launcher_path=str(self.paths.launcher))
            token = load_token()
            update_phase("DRAINING")
            response = self._request_graceful_shutdown(token)
            if response.status_code != 202:
                raise InstallationError(
                    f"Graceful shutdown was not accepted ({response.status_code}); task and service were not replaced."
                )

            deadline = time.monotonic() + timeout
            lock_path = Path(load_config(self.paths.config).service.state_persistence_path).with_suffix(".lock")
            while time.monotonic() < deadline:
                listener_state = _listener_identity_details()
                listener_closed = listener_state.get("category") == "not-found"
                if (self._service_status() is None and not self._coordinator_port_open() and listener_closed):
                    probe = SingleInstanceLock(lock_path)
                    service_alive = _exact_process_is_alive(
                        int(preflight["listener"]["pid"]), float(preflight["listener"]["create_time"])
                    )
                    if probe.acquire() and service_alive is False:
                        probe.release()
                        break
                    probe.release()
                time.sleep(0.25)
            else:
                raise InstallationError("Old coordinator did not release port 1235 and its instance lock in time")

            old_miner = preflight["miner"]
            if preflight["miner_resume_allowed"]:
                miner_alive = _exact_process_is_alive(int(old_miner["pid"]), float(old_miner["create_time"]))
                if miner_alive is not False:
                    raise InstallationError("Original coordinator-owned miner is still running; replacement refused")
            update_phase("OLD_STOPPED")

            self._write_managed(self.paths.launcher, render_launcher(self.paths))
            task_update_started = True
            task = self.task_backend.install(task.mode, self.paths.launcher, non_interactive=non_interactive)
            task_updated = True
            update_phase("TASK_UPDATED", task_after=asdict(task))
            self.task_backend.start(task, non_interactive=non_interactive)

            service = self._wait_for_service(timeout=timeout)
            if not service:
                raise InstallationError("Updated startup task did not produce a ready coordinator")
            runtime = service.get("runtime") or {}
            if runtime.get("revision") != preflight["source"]["revision"]:
                raise InstallationError("New coordinator is ready but its startup-captured source revision does not match")
            if service.get("upstream_url") != preflight["configured_upstream_url"]:
                raise InstallationError("New coordinator inference upstream does not match the protected configuration")
            if not _runtime_source_matches(runtime.get("source_path"), Path(preflight["source"]["source_path"])):
                raise InstallationError("New coordinator source path does not match the selected source checkout")
            if runtime.get("pid") == preflight["listener"]["pid"]:
                raise InstallationError("Coordinator PID did not change across the upgrade")
            new_listener = _listener_identity()
            if new_listener is None or new_listener.get("pid") != runtime.get("pid"):
                raise InstallationError("Ready coordinator PID does not own the port 1235 listener")
            new_create_time = runtime.get("process_create_time")
            if new_create_time is not None and not _same_process_creation_time(
                    new_create_time, new_listener["create_time"]):
                raise InstallationError("New coordinator runtime creation time does not match its listener")
            if new_create_time is None:
                raise InstallationError("New coordinator did not report a process creation time for listener verification")
            with httpx.Client(timeout=5.0) as client:
                control = client.get(f"{COORDINATOR_URL}/_coordinator/miner/status")
            if control.status_code != 200:
                raise InstallationError(f"New miner-control API is unavailable ({control.status_code})")

            effective = _effective_gpu_settings()
            expected_power = preflight["configured_gpu_settings"].get("power_limit_w")
            if expected_power is not None and (
                effective is None or effective.get("power_limit_w") is None or
                abs(float(effective["power_limit_w"]) - expected_power) > 0.5
            ):
                update_phase("RECOVERY_REQUIRED", new_runtime=runtime, effective_gpu_settings_after=effective,
                             blocker="effective GPU power limit does not match configured policy")
                return {"status": "recovery-required", "phase": "NEW_READY", "preflight": preflight,
                        "runtime": runtime, "effective_gpu_settings": effective,
                        "blocker": "Coordinator is ready, but mining was left stopped because GPU policy verification failed."}

            if preflight["miner_resume_allowed"]:
                response = httpx.post(
                    f"{COORDINATOR_URL}/_coordinator/miner/resume",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"operator": getpass.getuser(), "reason": "Resume prior mining state after verified upgrade"},
                    timeout=10.0,
                )
                if response.status_code != 200:
                    raise InstallationError(f"Prior miner state could not be safely restored ({response.status_code})")
                service = self._wait_for_service(timeout=10.0) or service
                miner_after = (service.get("processes") or {}).get(preflight["miner_name"], {})
                if miner_after.get("state") != "running" or not miner_after.get("is_coordinator_owned"):
                    raise InstallationError("Mining did not resume under the new coordinator's verified ownership")
            elif preflight["miner_name"]:
                miner_after = (service.get("processes") or {}).get(preflight["miner_name"], {})
                if miner_after.get("state") != "stopped":
                    raise InstallationError(
                        "Mining was held before upgrade but the new coordinator did not verify it stayed stopped"
                    )
            update_phase("VERIFIED", new_runtime=runtime, effective_gpu_settings_after=effective,
                         miner_after=(service.get("processes") or {}).get(preflight["miner_name"], {}))
            return {"status": "verified", "phase": "VERIFIED", "runtime": runtime,
                    "miner_was_running": preflight["miner_was_running"],
                    "miner_resumed": preflight["miner_resume_allowed"], "effective_gpu_settings": effective,
                    "receipt": str(self.paths.upgrade_receipt)}
        except Exception as exc:
            failed_at = receipt.get("phase", "UNKNOWN")
            if task_update_started and self._service_status() is None:
                try:
                    restorer = getattr(self.task_backend, "restore_snapshot")
                    restorer(task, preflight["task_snapshot"], non_interactive=non_interactive)
                    if original_launcher_text is None:
                        self.paths.launcher.unlink(missing_ok=True)
                    else:
                        self._write_managed(self.paths.launcher, original_launcher_text)
                    self.paths.upgrade_policy.unlink(missing_ok=True)
                    receipt["task_restored"] = True
                except Exception as restore_error:
                    receipt["task_restore_error"] = str(restore_error)
            elif not task_updated:
                try:
                    if original_launcher_text is None:
                        self.paths.launcher.unlink(missing_ok=True)
                    else:
                        self._write_managed(self.paths.launcher, original_launcher_text)
                    self.paths.upgrade_policy.unlink(missing_ok=True)
                except Exception as restore_error:
                    receipt["launcher_restore_error"] = str(restore_error)
            update_phase("RECOVERY_REQUIRED", failed_at=failed_at, error=str(exc))
            raise InstallationError(
                f"Upgrade stopped during {failed_at}; no process was force-terminated. "
                f"Inspect {self.paths.upgrade_receipt} before retrying. Details: {exc}"
            ) from exc

    @staticmethod
    def _service_status() -> Optional[Dict[str, Any]]:
        try:
            with httpx.Client(timeout=2.0) as client:
                response = client.get(f"{COORDINATOR_URL}/_coordinator/status")
            return response.json() if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None

    def _wait_for_service(self, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self._service_status()
            if status and status.get("service_state") == "ready":
                return status
            time.sleep(0.5)
        return None

    @staticmethod
    def _coordinator_port_open() -> bool:
        try:
            with socket.create_connection(("127.0.0.1", 1235), timeout=0.3):
                return True
        except OSError:
            return False

    @staticmethod
    def _request_graceful_shutdown(token: str) -> httpx.Response:
        with httpx.Client(timeout=60.0) as client:
            return client.post(
                f"{COORDINATOR_URL}/_coordinator/shutdown",
                headers={"Authorization": f"Bearer {token}"},
                json={"operator": os.environ.get("USERNAME", "operator"),
                      "reason": "Resource Coordinator teardown"},
            )

    def doctor(self) -> Dict[str, Any]:
        try:
            task_rows = [asdict(task) for task in self.task_backend.status()]
            task_inventory_error = None
        except Exception as exc:
            task_rows = []
            task_inventory_error = str(exc)
        checks: Dict[str, Any] = {
            "source_version": __import__("resource_coordinator").__version__,
            "source_path": str(Path(__file__).resolve()),
            "python_executable": str(Path(sys.executable).resolve()),
            "config_path": str(self.paths.config),
            "config_valid": False,
            "credential": credential_doctor(),
            "service": self._service_status(),
            "tasks": task_rows,
            "task_inventory_error": task_inventory_error,
        }
        configured_gpu_settings: Dict[str, float] = {}
        configured_limit: Optional[float] = None
        try:
            config = load_config(self.paths.config)
            checks["config_valid"] = True
            checks["processes"] = sorted(config.processes)
            configured_gpu_settings = _configured_gpu_settings(config)
            checks["configured_gpu_settings"] = configured_gpu_settings
            configured_limit = configured_gpu_settings.get("power_limit_w")
            checks["configured_power_limit_w"] = configured_limit
            checks["log_paths"] = {
                name: {
                    "path": str(log_path := _effective_log_path(name, process, self.paths.logs)),
                    "exists": log_path.is_file(),
                    "parent_writable": bool(
                        log_path.parent.exists() and os.access(log_path.parent, os.W_OK)
                    ),
                }
                for name, process in config.processes.items()
            }
            try:
                with httpx.Client(timeout=2.0) as client:
                    checks["upstream_ready"] = client.get(f"{config.service.upstream_url.rstrip('/')}/v1/models").status_code == 200
            except httpx.HTTPError:
                checks["upstream_ready"] = False
        except Exception as exc:
            checks["config_error"] = str(exc)
            config = None

        service = checks.get("service") or {}
        checks["service_ready"] = service.get("service_state") == "ready"
        runtime = service.get("runtime", {})
        expected_source = Path(__file__).resolve().parent / "__init__.py"
        expected_runtime = build_runtime_identity(self.paths.repository / "modules" / "resource_coordinator" /
                                                  "resource_coordinator")
        checks["runtime"] = runtime
        checks["runtime_source_matches"] = _runtime_source_matches(runtime.get("source_path"), expected_source)
        checks["runtime_version_matches"] = runtime.get("version") == checks["source_version"]
        checks["runtime_revision_matches"] = runtime.get("revision") == expected_runtime["revision"]
        checks["runtime_current"] = bool(
            checks["service_ready"] and checks["runtime_revision_matches"] and
            checks["runtime_version_matches"] and checks["runtime_source_matches"]
        )
        receipt = None
        if self.paths.upgrade_receipt.is_file():
            try:
                receipt = json.loads(self.paths.upgrade_receipt.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                receipt = {"phase": "CORRUPT"}
        receipt_phase = (receipt or {}).get("phase")
        checks["upgrade_in_progress"] = receipt_phase in {
            "PREPARED", "DRAINING", "OLD_STOPPED", "TASK_UPDATED", "NEW_READY"
        }
        checks["upgrade_blocked"] = receipt_phase == "RECOVERY_REQUIRED"
        checks["upgrade_available"] = bool(checks["service_ready"] and not checks["runtime_current"])
        checks["upgrade_recovery_required"] = checks["upgrade_blocked"] or receipt_phase == "CORRUPT"
        checks["upgrade_receipt_phase"] = receipt_phase
        checks["upgrade_state"] = (
            "recovery_required" if checks["upgrade_recovery_required"] else
            "in_progress" if checks["upgrade_in_progress"] else
            "available" if checks["upgrade_available"] else
            "current" if checks["runtime_current"] else "unknown"
        )
        gpu = service.get("gpu_inference", {})
        checks["active_inferences"] = gpu.get("active_count")
        checks["pending_requests"] = gpu.get("pending_count")
        miner = service.get("processes", {}).get("krig_miner", {})
        checks["miner"] = miner
        checks["miner_expected"] = bool(config and any("miner" in name.casefold() or "krig" in name.casefold() for name in config.processes))
        checks["miner_owned"] = bool(miner.get("is_coordinator_owned"))

        tasks = [task for task in checks["tasks"] if task["owned"] and task["mode"] in {"boot", "logon"}]
        checks["task_ready"] = any(
            task["enabled"] and task["run_level"] == "Highest" and _task_identity_valid(task)
            for task in tasks
        )
        if task_inventory_error:
            checks["task_ready"] = False
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,power.limit,power.draw,clocks.current.graphics,clocks.current.memory", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, check=True,
            )
            row = next(csv.reader([result.stdout.strip()]))
            def number(value: str) -> Optional[float]:
                try:
                    return float(value.strip())
                except ValueError:
                    return None

            checks["gpu"] = {
                "name": row[0],
                "power_limit_w": number(row[1]),
                "power_draw_w": number(row[2]),
                "graphics_clock_mhz": number(row[3]),
                "memory_clock_mhz": number(row[4]),
                "core_offset_mhz": None,
                "core_offset_note": "NVIDIA nvidia-smi does not expose an effective live offset in this query.",
            }
            checks["effective_power_limit_w"] = checks["gpu"]["power_limit_w"]
        except (OSError, subprocess.SubprocessError, ValueError, IndexError, StopIteration):
            checks["gpu"] = None

        observed_gpu = checks.get("gpu") or {}
        checks["gpu_policy_verification"] = {
            "power_limit_w": (
                "verified" if configured_limit is not None and observed_gpu.get("power_limit_w") is not None
                and abs(configured_limit - float(observed_gpu["power_limit_w"])) <= 0.5
                else "mismatch" if configured_limit is not None and observed_gpu.get("power_limit_w") is not None
                else "unavailable"
            ),
            "memory_clock_mhz": (
                "verified" if configured_gpu_settings.get("memory_clock_mhz") is not None
                and observed_gpu.get("memory_clock_mhz") is not None
                and abs(configured_gpu_settings["memory_clock_mhz"] - float(observed_gpu["memory_clock_mhz"])) <= 100
                else "mismatch" if configured_gpu_settings.get("memory_clock_mhz") is not None
                and observed_gpu.get("memory_clock_mhz") is not None
                else "unavailable"
            ),
            "core_clock_mhz": "observed_dynamic_only" if observed_gpu.get("graphics_clock_mhz") is not None else "unavailable",
            "core_offset_mhz": "unavailable",
        }

        checks["credential_ready"] = bool(
            checks["credential"].get("credential_valid")
            and checks["credential"].get("credential_file_readable")
            and checks["credential"].get("acl_restricted")
        )
        checks["installation_configured"] = bool(
            checks["config_valid"] and checks["credential_ready"] and checks["task_ready"]
        )
        checks.update(classify_doctor({
            "service_ready": checks["service_ready"],
            "runtime_source_matches": checks["runtime_source_matches"],
            "runtime_version_matches": checks["runtime_version_matches"],
            "runtime_revision_matches": checks["runtime_revision_matches"],
            "credential_ready": checks["credential_ready"],
            "task_ready": checks["task_ready"],
            "configured_power_limit_w": checks.get("configured_power_limit_w"),
            "effective_power_limit_w": checks.get("effective_power_limit_w"),
            "configured_gpu_settings": checks.get("configured_gpu_settings", {}),
            "gpu_policy_verification": checks.get("gpu_policy_verification", {}),
            "miner_expected": checks["miner_expected"],
            "miner_owned": checks["miner_owned"],
            "upstream_ready": checks.get("upstream_ready"),
            "log_paths": checks.get("log_paths", {}),
            "upgrade_in_progress": checks["upgrade_in_progress"],
            "upgrade_recovery_required": checks["upgrade_recovery_required"],
        }))
        return checks

    def teardown(self, *, apply: bool = False, non_interactive: bool = False) -> Dict[str, Any]:
        plan = self.plan_teardown()
        if not apply:
            return plan
        status = self._service_status()
        if status is None:
            return self._offline_teardown(plan, non_interactive=non_interactive)
        gpu = status.get("gpu_inference", {})
        if status.get("service_state") != "ready":
            raise InstallationError(
                f"Teardown refused because coordinator is not ready ({status.get('service_state')})."
            )
        if gpu.get("is_restart_inhibited"):
            raise InstallationError("Teardown refused while inference state is restart-inhibited.")
        try:
            config = load_config(self.paths.config)
            state_path = Path(config.service.state_persistence_path)
            if not config.service.state_persistence_path or not state_path.is_file():
                raise ValueError("durable state path is missing")
            StateCodec.load(state_path)
        except Exception as exc:
            raise InstallationError(
                "Teardown refused because a valid durable journal cannot be verified; no service state was changed."
            ) from exc
        owned_processes = [
            proc for proc in status.get("processes", {}).values()
            if proc.get("is_coordinator_owned") and proc.get("pid") and proc.get("create_time")
        ]
        try:
            token = load_token()
        except Exception as exc:
            raise InstallationError(
                "Cannot authenticate teardown with the existing operator credential; no resource was changed. "
                "Run 'resource-coordinator system auth doctor' offline and repair the credential first."
            ) from exc
        try:
            response = self._request_graceful_shutdown(token)
        except httpx.HTTPError as exc:
            raise InstallationError(f"Could not request graceful shutdown: {exc}") from exc
        if response.status_code != 202:
            raise InstallationError(f"Graceful coordinator shutdown failed ({response.status_code}).")
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if not self._coordinator_port_open():
                break
            time.sleep(0.5)
        else:
            raise InstallationError("Coordinator did not release its service port after shutdown.")
        try:
            lock_path = state_path.with_suffix(".lock")
            lock = SingleInstanceLock(lock_path)
            if not lock.acquire():
                raise InstallationError("Coordinator port closed but its instance lock remains held.")
        except InstallationError:
            raise
        except Exception as exc:
            raise InstallationError("Could not verify coordinator instance-lock release.") from exc
        try:
            if owned_processes:
                import psutil

                deadline = time.monotonic() + 15.0
                while time.monotonic() < deadline:
                    running = []
                    for proc in owned_processes:
                        try:
                            live = psutil.Process(int(proc["pid"]))
                            if live.create_time() == float(proc["create_time"]):
                                running.append(int(proc["pid"]))
                        except psutil.NoSuchProcess:
                            pass
                    if not running:
                        break
                    time.sleep(0.25)
                else:
                    raise InstallationError(f"Owned processes did not exit after coordinator shutdown: {running}")
            remaining = []
            for task in self.task_backend.status():
                if task.owned:
                    self.task_backend.uninstall(task, non_interactive=non_interactive)
                    remaining.append(task.name)
            removed = []
            for path in (self.paths.launcher, self.paths.viewer):
                if path.is_file() and TASK_MARKER in path.read_text(encoding="utf-8", errors="replace"):
                    path.unlink()
                    removed.append(str(path))
        finally:
            lock.release()
        return {"status": "applied", "tasks_uninstalled": remaining, "launchers_removed": removed,
                "preserved": plan["preserved"]}

    def _offline_teardown(self, plan: Dict[str, Any], *, non_interactive: bool) -> Dict[str, Any]:
        """Remove offline artifacts only when no live owned process needs its original supervisor."""
        try:
            config = load_config(self.paths.config)
            if not config.service.state_persistence_path:
                raise ValueError("durable state path is not configured")
            state_path = Path(config.service.state_persistence_path)
        except Exception as exc:
            raise InstallationError(
                "Coordinator is unreachable and its configuration cannot identify a durable journal; "
                "offline teardown made no changes. Restore the coordinator or configuration first."
            ) from exc

        lock_path = state_path.with_suffix(".lock")
        lock = SingleInstanceLock(lock_path)
        if not lock.acquire():
            raise InstallationError(
                "Coordinator is unreachable but its instance lock is held; offline teardown made no changes."
            )
        try:
            try:
                state = StateCodec.load(state_path)
            except Exception as exc:
                raise InstallationError(
                    "Coordinator is unreachable and durable state is missing, unreadable, or invalid; "
                    "offline teardown made no changes. Restore the coordinator or repair its journal first."
                ) from exc
            unresolved = [
                request.request_id for request in state.requests.values()
                if request.phase in {
                    RequestPhase.RESERVED.value,
                    RequestPhase.POSSIBLY_FORWARDED.value,
                    RequestPhase.UNCERTAIN.value,
                }
            ]
            if unresolved or state.inhibitions:
                raise InstallationError(
                    "Coordinator is unreachable and the journal contains unresolved inference or safety holds; "
                    "offline teardown made no changes."
                )
            if state.gaming_mode.get("state", "inactive") != "inactive":
                raise InstallationError(
                    "Coordinator is unreachable during a gaming-mode transition; offline teardown made no changes."
                )
            import psutil

            live_owned: List[int] = []
            uncertain_owned: List[str] = []
            for name, process in state.processes.items():
                if process.lifecycle_owner != ProcessLifecycleOwner.COORDINATOR.value or process.pid is None:
                    continue
                try:
                    actual = psutil.Process(process.pid)
                    actual_create_time = actual.create_time()
                except psutil.NoSuchProcess:
                    continue
                except (psutil.AccessDenied, psutil.Error) as exc:
                    uncertain_owned.append(f"{name} (PID {process.pid}: {exc})")
                    continue
                if process.create_time is None:
                    uncertain_owned.append(f"{name} (PID {process.pid}: missing creation time)")
                elif actual_create_time == process.create_time:
                    if "miner" in name.casefold() or "krig" in name.casefold():
                        live_owned.append(process.pid)
                    else:
                        uncertain_owned.append(f"{name} (PID {process.pid} still running)")
            if uncertain_owned:
                raise InstallationError(
                    "Offline teardown cannot verify all coordinator-owned process identities: "
                    + "; ".join(uncertain_owned)
                    + ". No task or process was changed."
                )
            if live_owned:
                raise InstallationError(
                    "Coordinator is unreachable while its miner is still running "
                    f"(verified PID(s): {live_owned}); the original coordinator's process-group handle "
                    "cannot be recovered by starting a new instance. Offline teardown therefore refuses "
                    "to stop the miner or remove its startup task. Restore coordinator control and retry "
                    "'resource-coordinator system teardown --apply'; if the original supervisor cannot be restored, "
                    "leave the miner and installation intact until the miner exits."
                )
            else:
                removed_tasks: List[str] = []
                for task in self.task_backend.status():
                    if task.owned:
                        self.task_backend.uninstall(task, non_interactive=non_interactive)
                        removed_tasks.append(task.name)
                removed_paths: List[str] = []
                for path in (self.paths.launcher, self.paths.viewer):
                    if path.is_file() and TASK_MARKER in path.read_text(encoding="utf-8", errors="replace"):
                        path.unlink()
                        removed_paths.append(str(path))
                result = {
                    "status": "applied",
                    "offline_recovery": True,
                    "tasks_uninstalled": removed_tasks,
                    "launchers_removed": removed_paths,
                    "preserved": plan["preserved"],
                }
        finally:
            lock.release()

        return result


_TASKS_POWERSHELL = r'''
$ErrorActionPreference = 'Stop'
$payload = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__PAYLOAD__')) | ConvertFrom-Json
$marker = 'ResourceCoordinator:Managed:v1'
$taskNames = @('ResourceCoordinator-KRig-Boot','ResourceCoordinator-KRig-UserLogon','KRig-Live-Output-Viewer')
$managedRoot = [IO.Path]::GetFullPath([string]$payload.managed_root)
$rootPrefix = $managedRoot.TrimEnd('\') + '\'
function Get-RcSid([string]$identity) {
  if ($identity -match '^S-1-\d+(?:-\d+)+$') { return $identity }
  return ([Security.Principal.NTAccount]$identity).Translate([Security.Principal.SecurityIdentifier]).Value
}
$interactiveSid = Get-RcSid ([string]$payload.interactive_user)
function Test-RcOwned($task) {
    if (-not $task) { return $false }
    try {
      if ($task.TaskName -eq 'ResourceCoordinator-KRig-Boot') {
        $taskSid = Get-RcSid ([string]$task.Principal.UserId)
        if ($taskSid -ne 'S-1-5-18') { return $false }
      } else {
        $taskSid = Get-RcSid ([string]$task.Principal.UserId)
        if ($taskSid -ne $interactiveSid) { return $false }
      }
    } catch { return $false }
    foreach ($action in $task.Actions) {
      if ($task.TaskName -in @('ResourceCoordinator-KRig-Boot','ResourceCoordinator-KRig-UserLogon') -and $action.Arguments -match '-File\s+"?(.+?start-coordinator(?:-managed)?\.ps1)') {
        try { if ([IO.Path]::GetFullPath($Matches[1]).StartsWith($rootPrefix,[StringComparison]::OrdinalIgnoreCase)) { return $true } } catch {}
      }
      if ($task.TaskName -eq 'KRig-Live-Output-Viewer' -and $action.Arguments -match '-File\s+"?(.+?view-krig(?:-managed)?\.ps1)') {
        try { if ([IO.Path]::GetFullPath($Matches[1]).StartsWith($rootPrefix,[StringComparison]::OrdinalIgnoreCase)) { return $true } } catch {}
      }
    }
    return $false
}
switch ($payload.operation) {
  'status' {
    $items = @()
    # Probe first without suppressing access errors. An inaccessible task store
    # must not be reported as an empty, healthy installation.
    $allTasks = @(Get-ScheduledTask -ErrorAction Stop)
    foreach ($name in $taskNames) {
      $task = $allTasks | Where-Object TaskName -EQ $name | Select-Object -First 1
      if (-not $task) { continue }
      $mode = if ($name -eq 'ResourceCoordinator-KRig-Boot') {'boot'} elseif ($name -eq 'ResourceCoordinator-KRig-UserLogon') {'logon'} else {'viewer'}
      $items += [pscustomobject]@{name=$name;mode=$mode;enabled=[bool]$task.Settings.Enabled;state=[string]$task.State;user_id=[string]$task.Principal.UserId;run_level=[string]$task.Principal.RunLevel;action=[string](($task.Actions|ForEach-Object {$_.Execute+' '+$_.Arguments}) -join ';');owned=(Test-RcOwned $task)}
    }
    ConvertTo-Json -InputObject @($items) -Depth 5 -Compress
  }
  {$_ -in 'install','install_viewer','enable','disable','uninstall','start','snapshot','restore'} {
    if ($payload.operation -eq 'install') {
      if ($payload.mode -notin @('boot','logon')) { throw 'Unsupported startup mode.' }
      $name = if ($payload.mode -eq 'boot') {'ResourceCoordinator-KRig-Boot'} else {'ResourceCoordinator-KRig-UserLogon'}
      $launcher = [IO.Path]::GetFullPath([string]$payload.launcher)
      if (-not $launcher.StartsWith($rootPrefix,[StringComparison]::OrdinalIgnoreCase) -or (Split-Path $launcher -Leaf) -ne 'start-coordinator-managed.ps1') { throw 'Launcher path is outside the managed installation.' }
      if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw 'Managed launcher is missing.' }
    } elseif ($payload.operation -eq 'install_viewer') {
      $name='KRig-Live-Output-Viewer'
      $launcher = [IO.Path]::GetFullPath([string]$payload.launcher)
      if (-not $launcher.StartsWith($rootPrefix,[StringComparison]::OrdinalIgnoreCase) -or (Split-Path $launcher -Leaf) -ne 'view-krig-managed.ps1') { throw 'Viewer path is outside the managed installation.' }
      if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw 'Managed viewer is missing.' }
    } else { $name=[string]$payload.task_name }
    if ($name -notin $taskNames) { throw 'Task name is not managed by Resource Coordinator.' }
    $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($existing -and -not (Test-RcOwned $existing)) { throw "Refusing to modify unowned task $name." }
    switch ($payload.operation) {
      'install' {
        $pwsh = (Get-Command pwsh.exe -ErrorAction SilentlyContinue).Source
        if (-not $pwsh) { $pwsh = (Get-Command powershell.exe -ErrorAction Stop).Source }
        $action = New-ScheduledTaskAction -Execute $pwsh -Argument ("-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File `"$launcher`"")
        if ($payload.mode -eq 'boot') {
          $trigger = New-ScheduledTaskTrigger -AtStartup
          $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
        } else {
          $user = [string]$payload.interactive_user
          $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
          $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
        }
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
        Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description $marker -Force | Out-Null
        $other = if ($payload.mode -eq 'boot') {'ResourceCoordinator-KRig-UserLogon'} else {'ResourceCoordinator-KRig-Boot'}
        $otherTask = Get-ScheduledTask -TaskName $other -ErrorAction SilentlyContinue
        if ($otherTask -and (Test-RcOwned $otherTask)) { Disable-ScheduledTask -TaskName $other | Out-Null }
      }
      'install_viewer' {
        $pwsh = (Get-Command pwsh.exe -ErrorAction SilentlyContinue).Source
        if (-not $pwsh) { $pwsh = (Get-Command powershell.exe -ErrorAction Stop).Source }
        $action = New-ScheduledTaskAction -Execute $pwsh -Argument ("-NoLogo -NoProfile -WindowStyle Normal -File `"$launcher`"")
        $user = [string]$payload.interactive_user
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
        $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
        Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description $marker -Force | Out-Null
      }
      'snapshot' {
        if (-not $existing -or -not (Test-RcOwned $existing)) { throw "Cannot snapshot missing or unowned task $name." }
        $definition = Export-ScheduledTask -TaskName $name -ErrorAction Stop
        ConvertTo-Json -Compress -InputObject @{definition=$definition; enabled=[bool]$existing.Settings.Enabled}
      }
      'restore' {
        if (-not $payload.definition -or $null -eq $payload.enabled) { throw 'Task recovery snapshot is incomplete.' }
        Register-ScheduledTask -TaskName $name -Xml ([string]$payload.definition) -Force | Out-Null
        if ([bool]$payload.enabled) { Enable-ScheduledTask -TaskName $name | Out-Null }
        else { Disable-ScheduledTask -TaskName $name | Out-Null }
      }
      'enable' { Enable-ScheduledTask -TaskName $name | Out-Null }
      'disable' { Disable-ScheduledTask -TaskName $name | Out-Null }
      'uninstall' { Unregister-ScheduledTask -TaskName $name -Confirm:$false }
      'start' { Start-ScheduledTask -TaskName $name }
    }
  }
  default { throw 'Unsupported Resource Coordinator task operation.' }
}
'''


def _powershell_backend(paths: InstallationPaths) -> WindowsStartupTaskBackend:
    return WindowsStartupTaskBackend(managed_root=paths.root)


def handle_installation_command(args: Any) -> int:
    """CLI entry point; command execution remains separate from core logic for testing."""
    from resource_coordinator.presentation import (
        emit_json, render_health_result, render_result, render_startup_status, render_upgrade_result,
    )

    paths = InstallationPaths.discover()
    backend = _powershell_backend(paths)
    manager = ManagedInstallation(paths, backend)
    if args.command == "upgrade":
        result = manager.upgrade(apply=args.apply, non_interactive=args.non_interactive)
        if getattr(args, "json", False):
            emit_json(result)
        else:
            render_upgrade_result(result)
        return 1 if result.get("status") in {"blocked", "recovery-required"} else 0
    if args.command == "setup":
        result = manager.setup(
            apply=args.apply, mode=args.startup_mode, non_interactive=args.non_interactive,
            viewer=getattr(args, "viewer", False),
        )
    elif args.command == "doctor":
        result = manager.doctor()
    elif args.command == "teardown":
        result = manager.teardown(apply=args.apply, non_interactive=args.non_interactive)
    elif args.command == "repair":
        result = manager.setup(apply=args.apply, non_interactive=args.non_interactive)
    elif args.command == "startup":
        action = args.startup_command
        if action == "status":
            result = manager.startup_status()
        elif action == "install":
            result = manager.startup(action, apply=args.apply, mode=args.mode,
                                     non_interactive=args.non_interactive)
        else:
            result = manager.startup(action, apply=args.apply,
                                     non_interactive=args.non_interactive)
    else:
        raise InstallationError(f"Unsupported installation command: {args.command}")
    if getattr(args, "json", False):
        emit_json(result)
    else:
        if args.command == "doctor":
            render_health_result(result)
        elif args.command == "startup" and getattr(args, "startup_command", None) == "status":
            render_startup_status(result)
        else:
            render_result(f"Resource Coordinator {args.command.title()}", result)
    return 0
