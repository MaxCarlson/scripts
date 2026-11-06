"""Self-managed installation paths and Windows startup-task control."""

from __future__ import annotations

import base64
import csv
import ctypes
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
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
            "if (-not (Test-Path -LiteralPath $state) -and $serveArgs -notcontains '--first-boot') { $serveArgs += '--first-boot' }",
            "Set-Location -LiteralPath $repoRoot",
            "& $python @serveArgs *>> $log",
            "exit $LASTEXITCODE",
            "",
        ]
    )


def classify_doctor(checks: Dict[str, Any]) -> Dict[str, Any]:
    """Classify collected facts without allowing an HTTP 200 to mask degraded operation."""
    warnings: List[str] = []
    blockers: List[str] = []
    if checks.get("service_ready") is not True:
        blockers.append("coordinator service is not ready")
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
    if checks.get("miner_expected") and checks.get("miner_owned") is not True:
        warnings.append("configured miner is not running under coordinator ownership")
    if checks.get("upstream_ready") is False:
        warnings.append("configured inference upstream is not responding")
    return {
        "status": "blocked" if blockers else ("degraded" if warnings else "healthy"),
        "warnings": warnings,
        "blockers": blockers,
    }


class WindowsStartupTaskBackend:
    """Manage only the named RC tasks, using the built-in ScheduledTasks module."""

    def __init__(self, *, powershell: Optional[str] = None):
        self.powershell = powershell or shutil.which("pwsh.exe") or shutil.which("powershell.exe") or "powershell.exe"

    @staticmethod
    def _admin() -> bool:
        if os.name != "nt":
            return False
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False

    @staticmethod
    def _script(payload: Dict[str, Any]) -> str:
        payload_b64 = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
        return _TASKS_POWERSHELL.replace("__PAYLOAD__", payload_b64)

    def _run(self, payload: Dict[str, Any], *, elevated: bool = False,
             non_interactive: bool = False) -> subprocess.CompletedProcess[str]:
        if os.name != "nt":
            raise InstallationError("Windows Scheduled Tasks are available only on Windows")
        script = self._script(payload)
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        if elevated and not self._admin():
            if non_interactive:
                raise ElevationRequired("Administrator approval is required; rerun interactively or elevate PowerShell.")
            wrapper = (
                "$encoded=$env:RC_ELEVATED_SCRIPT; "
                "$p=Start-Process -FilePath $env:RC_POWERSHELL -Verb RunAs "
                "-ArgumentList @('-NoProfile','-NonInteractive','-EncodedCommand',$encoded) -Wait -PassThru; "
                "exit $p.ExitCode"
            )
            wrapper_encoded = base64.b64encode(wrapper.encode("utf-16le")).decode("ascii")
            result = subprocess.run(
                [self.powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", wrapper_encoded],
                env={**os.environ, "RC_ELEVATED_SCRIPT": encoded, "RC_POWERSHELL": self.powershell},
                capture_output=True, text=True, timeout=120,
            )
        else:
            result = subprocess.run(
                [self.powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                capture_output=True, text=True, timeout=120,
            )
        if result.returncode:
            message = _clean_powershell_error(result.stderr or result.stdout) or f"PowerShell exited {result.returncode}"
            if "access is denied" in message.casefold() or "requires elevation" in message.casefold():
                raise ElevationRequired(message)
            raise InstallationError(message)
        return result

    def status(self) -> List[StartupTask]:
        result = self._run({"operation": "status"})
        try:
            raw = json.loads(result.stdout or "[]")
            return [StartupTask(**task) for task in raw]
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            raise InstallationError("Scheduled Task status returned invalid data") from exc

    def install(self, mode: str, launcher: Path, *, non_interactive: bool = False) -> StartupTask:
        if mode not in {"boot", "logon"}:
            raise InstallationError(f"Unsupported startup mode: {mode}")
        self._run({"operation": "install", "mode": mode, "launcher": str(launcher)}, elevated=True,
                  non_interactive=non_interactive)
        result = next((task for task in self.status() if task.name == TASK_NAMES[mode]), None)
        if result is None or not result.owned:
            raise InstallationError(f"Scheduled Task {TASK_NAMES[mode]} was not installed as an RC-owned task")
        return result

    def set_enabled(self, task: StartupTask, enabled: bool, *, non_interactive: bool = False) -> StartupTask:
        if not task.owned:
            raise InstallationError(f"Refusing to change unowned Scheduled Task {task.name}")
        self._run({"operation": "enable" if enabled else "disable", "task_name": task.name}, elevated=True,
                  non_interactive=non_interactive)
        return next(item for item in self.status() if item.name == task.name)

    def uninstall(self, task: StartupTask, *, non_interactive: bool = False) -> None:
        if not task.owned:
            raise InstallationError(f"Refusing to remove unowned Scheduled Task {task.name}")
        self._run({"operation": "uninstall", "task_name": task.name}, elevated=True,
                  non_interactive=non_interactive)

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

    def plan_setup(self, mode: str = "logon") -> Dict[str, Any]:
        if mode not in {"boot", "logon"}:
            raise InstallationError(f"Unsupported startup mode: {mode}")
        return {
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
              activate: bool = True) -> Dict[str, Any]:
        plan = self.plan_setup(mode)
        if not apply:
            return {"status": "planned", **plan}
        if not self.template.is_file() and not self.paths.config.is_file():
            raise InstallationError(f"Configuration template is missing: {self.template}")
        created: List[str] = []
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self.paths.logs.mkdir(parents=True, exist_ok=True)
        self.paths.token.parent.mkdir(parents=True, exist_ok=True)
        if not self.paths.config.exists():
            shutil.copy2(self.template, self.paths.config)
            created.append("configuration")
        # Validation is read-only; existing comments and settings are preserved byte-for-byte.
        config = load_config(self.paths.config)
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
                "Run 'resource-coordinator auth doctor' and repair its ACL or explicitly reinitialize it."
            )
        if self._write_managed(self.paths.launcher, render_launcher(self.paths)):
            created.append("launcher")
        task = self.task_backend.install(mode, self.paths.launcher, non_interactive=non_interactive)
        task = self.task_backend.set_enabled(task, True, non_interactive=non_interactive)
        service = self._service_status() if activate else None
        activation = "not-started-by-startup-command" if not activate else "already-running"
        if activate:
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
        return {
            "status": "applied" if successful_activation and mining_warning is None else "degraded",
            "created": created,
            "task": asdict(task),
            "config_path": str(self.paths.config),
            "processes_configured": sorted(config.processes),
            "miner_identity_configured": miner_name is not None,
            "mining_warning": mining_warning,
            "service_activation": activation,
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
        try:
            config = load_config(self.paths.config)
            checks["config_valid"] = True
            checks["processes"] = sorted(config.processes)
            checks["configured_gpu_settings"] = _configured_gpu_settings(config)
            configured_limit = checks["configured_gpu_settings"].get("power_limit_w")
            checks["configured_power_limit_w"] = configured_limit
            checks["log_paths"] = {
                name: {
                    "path": process.stdout_log_path,
                    "exists": bool(process.stdout_log_path and Path(process.stdout_log_path).is_file()),
                    "parent_writable": bool(
                        process.stdout_log_path and Path(process.stdout_log_path).parent.exists()
                        and os.access(Path(process.stdout_log_path).parent, os.W_OK)
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

        checks["credential_ready"] = bool(
            checks["credential"].get("credential_valid")
            and checks["credential"].get("credential_file_readable")
            and checks["credential"].get("acl_restricted")
        )
        checks.update(classify_doctor({
            "service_ready": checks["service_ready"],
            "credential_ready": checks["credential_ready"],
            "task_ready": checks["task_ready"],
            "configured_power_limit_w": checks.get("configured_power_limit_w"),
            "effective_power_limit_w": checks.get("effective_power_limit_w"),
            "miner_expected": checks["miner_expected"],
            "miner_owned": checks["miner_owned"],
            "upstream_ready": checks.get("upstream_ready"),
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
        if int(gpu.get("active_count", 0)) or int(gpu.get("pending_count", 0)):
            raise InstallationError("Teardown refused while inference is active or pending.")
        if gpu.get("is_restart_inhibited"):
            raise InstallationError("Teardown refused while inference state is restart-inhibited.")
        owned_processes = [
            proc for proc in status.get("processes", {}).values()
            if proc.get("is_coordinator_owned") and proc.get("pid") and proc.get("create_time")
        ]
        try:
            token = load_token()
        except Exception as exc:
            raise InstallationError(
                "Cannot authenticate teardown with the existing operator credential; no resource was changed. "
                "Run 'resource-coordinator auth doctor' offline and repair the credential first."
            ) from exc
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    f"{COORDINATOR_URL}/_coordinator/shutdown",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"operator": os.environ.get("USERNAME", "operator"), "reason": "Resource Coordinator teardown"},
                )
        except httpx.HTTPError as exc:
            raise InstallationError(f"Could not request graceful shutdown: {exc}") from exc
        if response.status_code != 202:
            raise InstallationError(f"Graceful coordinator shutdown failed ({response.status_code}).")
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if self._service_status() is None:
                break
            time.sleep(0.5)
        else:
            raise InstallationError("Coordinator did not release its service port after shutdown.")
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
        return {"status": "applied", "tasks_uninstalled": remaining, "launchers_removed": removed,
                "preserved": plan["preserved"]}

    def _offline_teardown(self, plan: Dict[str, Any], *, non_interactive: bool) -> Dict[str, Any]:
        """Remove startup artifacts only when the lock and durable state prove it is safe.

        A running coordinator-owned process cannot be stopped here: the service's
        process-group handle is gone, so the offline path deliberately refuses
        to signal it and leaves startup resources intact.
        """
        try:
            config = load_config(self.paths.config)
            state_path = Path(config.service.state_persistence_path)
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

        lock_path = state_path.with_suffix(".lock")
        lock = SingleInstanceLock(lock_path)
        if not lock.acquire():
            raise InstallationError(
                "Coordinator is unreachable but its instance lock is held; offline teardown made no changes."
            )
        try:
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
                    f"(verified PID(s): {live_owned}); no safe process-group handle is available, "
                    "so no task or process was changed. Restore coordinator service, stop the miner "
                    "through its control API, then retry teardown."
                )

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
            return {
                "status": "applied",
                "offline_recovery": True,
                "tasks_uninstalled": removed_tasks,
                "launchers_removed": removed_paths,
                "preserved": plan["preserved"],
            }
        finally:
            lock.release()


_TASKS_POWERSHELL = r'''
$ErrorActionPreference = 'Stop'
$payload = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__PAYLOAD__')) | ConvertFrom-Json
$marker = 'ResourceCoordinator:Managed:v1'
$taskNames = @('ResourceCoordinator-KRig-Boot','ResourceCoordinator-KRig-UserLogon','KRig-Live-Output-Viewer')
function Test-RcOwned($task) {
    if (-not $task) { return $false }
    if ($task.Description -like "*$marker*") { return $true }
    $root = [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE '.resource_coordinator'))
    foreach ($action in $task.Actions) {
      if ($task.TaskName -in @('ResourceCoordinator-KRig-Boot','ResourceCoordinator-KRig-UserLogon') -and $action.Arguments -match '-File\s+"?(.+?start-coordinator(?:-managed)?\.ps1)') {
        try { if ([IO.Path]::GetFullPath($Matches[1]).StartsWith($root,[StringComparison]::OrdinalIgnoreCase)) { return $true } } catch {}
      }
      if ($task.TaskName -eq 'KRig-Live-Output-Viewer' -and $action.Arguments -match '-File\s+"?(.+?view-krig(?:-managed)?\.ps1)') {
        try { if ([IO.Path]::GetFullPath($Matches[1]).StartsWith($root,[StringComparison]::OrdinalIgnoreCase)) { return $true } } catch {}
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
  {$_ -in 'install','enable','disable','uninstall','start'} {
    if ($payload.operation -eq 'install') {
      if ($payload.mode -notin @('boot','logon')) { throw 'Unsupported startup mode.' }
      $name = if ($payload.mode -eq 'boot') {'ResourceCoordinator-KRig-Boot'} else {'ResourceCoordinator-KRig-UserLogon'}
      $launcher = [IO.Path]::GetFullPath([string]$payload.launcher)
      $expectedRoot = [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE '.resource_coordinator'))
      if (-not $launcher.StartsWith($expectedRoot,[StringComparison]::OrdinalIgnoreCase) -or (Split-Path $launcher -Leaf) -ne 'start-coordinator-managed.ps1') { throw 'Launcher path is outside the managed installation.' }
      if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw 'Managed launcher is missing.' }
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
          $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
          $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
          $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
        }
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
        Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description $marker -Force | Out-Null
        $other = if ($payload.mode -eq 'boot') {'ResourceCoordinator-KRig-UserLogon'} else {'ResourceCoordinator-KRig-Boot'}
        $otherTask = Get-ScheduledTask -TaskName $other -ErrorAction SilentlyContinue
        if ($otherTask -and (Test-RcOwned $otherTask)) { Disable-ScheduledTask -TaskName $other | Out-Null }
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


def _powershell_backend() -> WindowsStartupTaskBackend:
    return WindowsStartupTaskBackend()


def handle_installation_command(args: Any) -> int:
    """CLI entry point; command execution remains separate from core logic for testing."""
    paths = InstallationPaths.discover()
    backend = _powershell_backend()
    manager = ManagedInstallation(paths, backend)
    if args.command == "setup":
        result = manager.setup(apply=args.apply, mode=args.startup_mode, non_interactive=args.non_interactive)
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
        print(json.dumps(result, indent=2))
    else:
        status = result.get("status", "reported")
        print(f"Resource Coordinator {args.command}: {status}")
        for key, value in result.items():
            if key == "status":
                continue
            print(f"{key.replace('_', ' ').capitalize()}: {value}")
    return 0
