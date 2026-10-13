"""Generic JSON-driven monitor rules and safe process supervision."""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

import psutil

from .models import ShellEnvironment, Task


@dataclass
class MonitorCondition:
    """A comparison against a JSON field, optionally aggregated over a window."""

    path: str
    operator: str
    value: Any
    aggregation: str = "latest"
    window_seconds: int = 0
    hold_seconds: int = 0

    def __post_init__(self) -> None:
        if not self.path or self.operator not in {"eq", "ne", "gt", "gte", "lt", "lte"}:
            raise ValueError("Condition requires a field path and a supported operator.")
        if self.aggregation not in {"latest", "average", "min", "max"}:
            raise ValueError("Condition aggregation must be latest, average, min, or max.")
        if self.window_seconds < 0 or self.hold_seconds < 0:
            raise ValueError("Condition window and hold durations cannot be negative.")
        if self.aggregation != "latest" and not isinstance(self.value, (int, float)):
            raise ValueError("Window aggregations require a numeric comparison value.")
        if self.aggregation != "latest" and self.window_seconds == 0:
            raise ValueError("Average, min, and max aggregations require a nonzero window_seconds.")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MonitorCondition":
        return cls(**data)


@dataclass
class MonitoredProcess:
    """User-authored monitor command and the process it is allowed to manage."""

    name: str
    executable: str
    monitor_code: str = ""
    environment: str = ShellEnvironment.PWSH.value
    arguments: List[str] = field(default_factory=list)
    working_directory: Optional[str] = None
    monitor_file: Optional[str] = None
    monitor_arguments: List[str] = field(default_factory=list)
    new_console: bool = False
    interval_seconds: int = 30
    timeout_seconds: int = 10
    restart_cooldown_seconds: int = 60
    start_conditions: List[MonitorCondition] = field(default_factory=list)
    stop_conditions: List[MonitorCondition] = field(default_factory=list)
    enabled: bool = True
    rule_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        self.name = str(self.name or "").strip()
        self.executable = str(self.executable or "").strip()
        self.monitor_code = str(self.monitor_code or "")
        self.start_conditions = [
            item if isinstance(item, MonitorCondition) else MonitorCondition.from_dict(item)
            for item in self.start_conditions
        ]
        self.stop_conditions = [
            item if isinstance(item, MonitorCondition) else MonitorCondition.from_dict(item)
            for item in self.stop_conditions
        ]
        self.arguments = [str(value) for value in self.arguments]
        self.monitor_arguments = [str(value) for value in self.monitor_arguments]
        if not self.name or not self.executable or not (self.monitor_code.strip() or self.monitor_file):
            raise ValueError("A monitor needs a name, process executable, and monitor command or script file.")
        if self.environment not in {"pwsh", "powershell", "terminal"}:
            raise ValueError("Environment must be pwsh, powershell, or terminal.")
        if self.interval_seconds < 1 or self.timeout_seconds < 1 or self.restart_cooldown_seconds < 0:
            raise ValueError("Monitor interval and timeout must be at least one second; cooldown cannot be negative.")
        if not self.start_conditions or not self.stop_conditions:
            raise ValueError("At least one start condition and one stop condition are required.")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MonitoredProcess":
        raw = dict(data)
        raw["start_conditions"] = [
            item if isinstance(item, MonitorCondition) else MonitorCondition.from_dict(item)
            for item in raw.get("start_conditions", [])
        ]
        raw["stop_conditions"] = [
            item if isinstance(item, MonitorCondition) else MonitorCondition.from_dict(item)
            for item in raw.get("stop_conditions", [])
        ]
        return cls(**raw)

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        return result


def _field_value(document: Any, path: str) -> Any:
    value = document
    for component in path.split("."):
        if isinstance(value, dict) and component in value:
            value = value[component]
        elif isinstance(value, list) and component.isdigit() and int(component) < len(value):
            value = value[int(component)]
        else:
            raise KeyError(path)
    return value


def discover_fields(document: Any, prefix: str = "") -> Dict[str, str]:
    """Return leaf JSON paths and their types for preview/condition authoring."""
    fields: Dict[str, str] = {}
    if isinstance(document, dict):
        for key, value in document.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            fields.update(discover_fields(value, path))
    elif isinstance(document, list):
        if document:
            fields.update(discover_fields(document[0], f"{prefix}.0" if prefix else "0"))
        else:
            fields[prefix] = "array"
    else:
        fields[prefix] = "null" if document is None else type(document).__name__
    return fields


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    if operator in {"eq", "ne"}:
        equal = actual == expected and isinstance(actual, bool) == isinstance(expected, bool)
        return equal if operator == "eq" else not equal
    if isinstance(actual, bool) or isinstance(expected, bool) or not isinstance(actual, (int, float)):
        return False
    if not isinstance(expected, (int, float)):
        return False
    return {"gt": actual > expected, "gte": actual >= expected, "lt": actual < expected, "lte": actual <= expected}[operator]


class ConditionTracker:
    """Evaluate fresh samples and maintain rolling field values and hold timers."""

    def __init__(self) -> None:
        self.samples: List[Tuple[float, Any]] = []
        self.true_since: Dict[str, float] = {}
        self.last_true_sample: Dict[str, float] = {}

    def add(self, document: Any, now: Optional[float] = None, keep_seconds: int = 3600) -> None:
        timestamp = time.monotonic() if now is None else now
        self.samples.append((timestamp, document))
        cutoff = timestamp - max(keep_seconds, 1)
        self.samples = [(stamp, sample) for stamp, sample in self.samples if stamp >= cutoff]

    def matches(
        self, conditions: Sequence[MonitorCondition], now: Optional[float] = None,
        max_sample_gap: Optional[float] = None,
    ) -> bool:
        timestamp = time.monotonic() if now is None else now
        if not self.samples:
            return False
        for condition in conditions:
            key = json.dumps(asdict(condition), sort_keys=True)
            matching_samples = [
                (stamp, sample) for stamp, sample in self.samples
                if stamp >= timestamp - condition.window_seconds
            ]
            if not matching_samples:
                self.true_since.pop(key, None)
                self.last_true_sample.pop(key, None)
                return False
            try:
                values = [(stamp, _field_value(sample, condition.path)) for stamp, sample in matching_samples]
            except KeyError:
                self.true_since.pop(key, None)
                self.last_true_sample.pop(key, None)
                return False
            if condition.window_seconds and values[0][0] > timestamp - condition.window_seconds + 1.0:
                self.true_since.pop(key, None)
                self.last_true_sample.pop(key, None)
                return False
            if max_sample_gap and any(
                current[0] - previous[0] > max_sample_gap
                for previous, current in zip(values, values[1:])
            ):
                self.true_since.pop(key, None)
                self.last_true_sample.pop(key, None)
                return False
            if condition.aggregation == "latest":
                actual = values[-1][1]
            else:
                numeric = [float(v) for _, v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
                if len(numeric) != len(values) or not numeric:
                    self.true_since.pop(key, None)
                    self.last_true_sample.pop(key, None)
                    return False
                actual = sum(numeric) / len(numeric) if condition.aggregation == "average" else (
                    min(numeric) if condition.aggregation == "min" else max(numeric)
                )
            if not _compare(actual, condition.operator, condition.value):
                self.true_since.pop(key, None)
                self.last_true_sample.pop(key, None)
                return False
            latest_sample = values[-1][0]
            prior_sample = self.last_true_sample.get(key)
            if max_sample_gap and prior_sample is not None and latest_sample - prior_sample > max_sample_gap:
                self.true_since.pop(key, None)
            since = self.true_since.setdefault(key, latest_sample)
            self.last_true_sample[key] = latest_sample
            if condition.hold_seconds and latest_sample - since < condition.hold_seconds:
                return False
        return True


class MonitoredProcessManager:
    """Non-blocking monitor runner and PID-verified process lifecycle manager."""

    def __init__(self, storage: Any, executor: Any, logger: Any, history: Any = None) -> None:
        self.storage, self.executor, self.logger = storage, executor, logger
        self.history = history
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="scheduler-monitor")
        self._futures: Dict[str, Future] = {}
        self._due: Dict[str, float] = {}
        self._trackers: Dict[str, ConditionTracker] = {}
        self._last_errors: Dict[str, str] = {}
        self._processes: Dict[str, subprocess.Popen] = {}
        self._restart_after: Dict[str, float] = {}
        self._rule_cooldowns: Dict[str, int] = {}
        self._last_documents: Dict[str, Any] = {}

    def _record_event(self, rule: MonitoredProcess, event_type: str, message: str, **kwargs: Any) -> None:
        if self.history is None:
            return
        try:
            self.history.record_monitor_event(rule, event_type, message, **kwargs)
        except Exception as exc:
            self.logger.log_warning(f"Could not record monitor '{rule.name}' history: {exc}")

    def _record_action(
        self, rule: MonitoredProcess, action: str, *, origin: str, success: bool,
        started_at: str, duration_sec: float, message: str,
    ) -> None:
        if self.history is None:
            return
        try:
            self.history.record_monitor_action(
                rule, action, origin=origin, success=success, started_at=started_at,
                duration_sec=duration_sec, message=message,
            )
        except Exception as exc:
            self.logger.log_warning(f"Could not record monitor '{rule.name}' history: {exc}")

    def _run_probe(self, rule: MonitoredProcess) -> Any:
        code = rule.monitor_code
        if rule.monitor_file:
            monitor_path = Path(rule.monitor_file)
            if not monitor_path.is_absolute() and rule.working_directory:
                monitor_path = Path(rule.working_directory) / monitor_path
            if rule.environment in {"pwsh", "powershell"}:
                def quote(value: Any) -> str:
                    return "'" + str(value).replace("'", "''") + "'"
                arguments = [
                    value if re.fullmatch(r"-[A-Za-z_][A-Za-z0-9_-]*", value) else quote(value)
                    for value in rule.monitor_arguments
                ]
                code = "& " + " ".join([quote(monitor_path), *arguments])
            else:
                code = shlex.join([str(monitor_path), *rule.monitor_arguments])
        task = Task(name=f"Monitor: {rule.name}", environment=rule.environment, code=code)
        result = self.executor.execute(
            task, timeout_sec=rule.timeout_seconds, working_directory=rule.working_directory
        )
        if not result.success:
            raise RuntimeError(result.error_message or result.stderr or f"Monitor exited {result.exit_code}")
        if len(result.stdout.encode("utf-8", errors="replace")) > 1_048_576:
            raise ValueError("Monitor output exceeds the 1 MiB JSON limit.")
        document = json.loads(result.stdout)
        if not isinstance(document, dict):
            raise ValueError("Monitor stdout must contain one JSON object.")
        return document

    def _state(self) -> Dict[str, Any]:
        return self.storage.get_monitor_runtime_state()

    def _save_owned(self, rule_id: str, process: psutil.Process) -> None:
        state = self._state()
        state[rule_id] = {"pid": process.pid, "create_time": process.create_time(), "executable": process.exe()}
        self.storage.save_monitor_runtime_state(state)

    def _owned_process(self, rule_id: str, expected_executable: Optional[str] = None) -> Optional[psutil.Process]:
        state = self._state().get(rule_id)
        if not state:
            return None
        try:
            process = psutil.Process(int(state["pid"]))
            if abs(process.create_time() - float(state["create_time"])) > 0.01:
                raise psutil.NoSuchProcess(process.pid)
            if os.path.normcase(os.path.realpath(process.exe())) != os.path.normcase(os.path.realpath(state["executable"])):
                raise psutil.NoSuchProcess(process.pid)
            if expected_executable and not self._same_executable(process, expected_executable):
                raise psutil.NoSuchProcess(process.pid)
            return process
        except (KeyError, TypeError, ValueError, psutil.Error, OSError):
            current = self._state()
            current.pop(rule_id, None)
            self.storage.save_monitor_runtime_state(current)
            self._processes.pop(rule_id, None)
            if state:
                self._restart_after[rule_id] = time.monotonic() + self._rule_cooldowns.get(rule_id, 60)
            return None

    @staticmethod
    def _same_executable(process: psutil.Process, executable: str) -> bool:
        try:
            expected = os.path.normcase(os.path.realpath(executable))
            actual = os.path.normcase(os.path.realpath(process.exe()))
            return actual == expected or (not os.path.isabs(executable) and process.name().casefold() == Path(executable).name.casefold())
        except (psutil.Error, OSError):
            return False

    def _externally_running(self, rule: MonitoredProcess) -> bool:
        return any(self._same_executable(process, rule.executable) for process in psutil.process_iter(["name", "exe"]))

    def start(self, rule: MonitoredProcess, *, origin: str = "manual") -> str:
        started = time.time()
        started_at = datetime.now().astimezone().isoformat()
        self._rule_cooldowns[rule.rule_id] = rule.restart_cooldown_seconds
        if self._owned_process(rule.rule_id, rule.executable):
            self._record_event(rule, "MONITOR_START_SKIPPED", "Process is already running and owned by this monitor.", metadata={"origin": origin})
            return "already running (owned)"
        if self._externally_running(rule):
            self._record_event(rule, "MONITOR_START_SKIPPED", "Matching process is already running externally; it was not adopted.", metadata={"origin": origin})
            return "already running (external; not adopted)"
        launch_options: Dict[str, Any] = {"cwd": rule.working_directory or None, "shell": False}
        if rule.new_console and os.name == "nt":
            launch_options["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10)
        else:
            launch_options.update(
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        try:
            proc = subprocess.Popen([rule.executable, *rule.arguments], **launch_options)
            process = psutil.Process(proc.pid)
            self._processes[rule.rule_id] = proc
            self._save_owned(rule.rule_id, process)
            message = f"started (PID {proc.pid})"
            self.logger.log_system_info(f"Monitored process '{rule.name}' {message}.")
            self._record_action(
                rule, "start", origin=origin, success=True, started_at=started_at,
                duration_sec=time.time() - started, message=message,
            )
            return message
        except Exception as exc:
            message = f"start failed: {exc}"
            self._record_action(
                rule, "start", origin=origin, success=False, started_at=started_at,
                duration_sec=time.time() - started, message=message,
            )
            raise

    def stop(self, rule: MonitoredProcess, timeout_seconds: float = 10.0, *, origin: str = "manual") -> str:
        started = time.time()
        started_at = datetime.now().astimezone().isoformat()
        process = self._owned_process(rule.rule_id, rule.executable)
        if process is None:
            self._record_event(rule, "MONITOR_STOP_SKIPPED", "No scheduler-owned process is running for this monitor.", metadata={"origin": origin})
            return "not running as a scheduler-owned process"
        try:
            popen = self._processes.get(rule.rule_id)
            if popen is not None:
                popen.terminate()
                try:
                    popen.wait(timeout=timeout_seconds)
                except subprocess.TimeoutExpired:
                    popen.kill()
                    popen.wait(timeout=timeout_seconds)
            else:
                process.terminate()
                try:
                    process.wait(timeout=timeout_seconds)
                except psutil.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=timeout_seconds)
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            pass
        except Exception as exc:
            message = f"stop failed: {exc}"
            self._record_action(
                rule, "stop", origin=origin, success=False, started_at=started_at,
                duration_sec=time.time() - started, message=message,
            )
            raise
        try:
            state = self._state()
            state.pop(rule.rule_id, None)
            self.storage.save_monitor_runtime_state(state)
            self._processes.pop(rule.rule_id, None)
            self._restart_after[rule.rule_id] = time.monotonic() + rule.restart_cooldown_seconds
            self.logger.log_system_info(f"Monitored process '{rule.name}' stopped.")
            self._record_action(
                rule, "stop", origin=origin, success=True, started_at=started_at,
                duration_sec=time.time() - started, message="stopped",
            )
            return "stopped"
        except Exception as exc:
            message = f"stop failed after signaling process: {exc}"
            self._record_action(
                rule, "stop", origin=origin, success=False, started_at=started_at,
                duration_sec=time.time() - started, message=message,
            )
            raise

    def test(self, rule: MonitoredProcess) -> Any:
        """Run one probe synchronously for the explicit preview/test command."""
        try:
            output = self._run_probe(rule)
        except Exception as exc:
            self._record_event(rule, "MONITOR_PROBE_TEST_FAILED", str(exc), level="ERROR")
            raise
        self._record_event(rule, "MONITOR_PROBE_TESTED", "Explicit monitor probe completed successfully.")
        return output

    def tick(self) -> None:
        """Harvest completed probes and queue due enabled rules without blocking."""
        now = time.monotonic()
        rules = {rule.rule_id: rule for rule in self.storage.list_monitored_processes()}
        for rule_id, future in list(self._futures.items()):
            if not future.done():
                continue
            del self._futures[rule_id]
            rule = rules.get(rule_id)
            if rule is None or not rule.enabled:
                continue
            try:
                document = future.result()
            except Exception as exc:
                message = str(exc)
                if self._last_errors.get(rule_id) != message:
                    self.logger.log_warning(f"Monitor '{rule.name}' has unknown output: {message}")
                    self._record_event(rule, "MONITOR_PROBE_FAILED", message, level="ERROR")
                self._last_errors[rule_id] = message
                continue
            if self._last_errors.pop(rule_id, None) is not None:
                self._record_event(rule, "MONITOR_PROBE_RECOVERED", "Monitor probe is producing valid output again.")
            try:
                tracker = self._trackers.setdefault(rule_id, ConditionTracker())
                keep_seconds = max(
                    [condition.window_seconds for condition in rule.start_conditions + rule.stop_conditions]
                    + [3600]
                )
                tracker.add(document, now, keep_seconds=keep_seconds)
                self._last_documents[rule_id] = document
                self._last_errors.pop(rule_id, None)
                if self._owned_process(rule_id, rule.executable):
                    if tracker.matches(rule.stop_conditions, now, max_sample_gap=rule.interval_seconds * 2.5):
                        self.stop(rule, origin="automatic")
                elif (
                    now >= self._restart_after.get(rule_id, 0)
                    and not self._externally_running(rule)
                    and tracker.matches(
                        rule.start_conditions, now, max_sample_gap=rule.interval_seconds * 2.5
                    )
                ):
                    self.start(rule, origin="automatic")
            except Exception as exc:
                message = str(exc)
                self.logger.log_warning(f"Monitor '{rule.name}' evaluation failed: {message}")
                self._record_event(rule, "MONITOR_EVALUATION_FAILED", message, level="ERROR")
        for rule_id, rule in rules.items():
            self._rule_cooldowns[rule_id] = rule.restart_cooldown_seconds
            if not rule.enabled or rule_id in self._futures or now < self._due.get(rule_id, 0):
                continue
            self._due[rule_id] = now + rule.interval_seconds
            self._futures[rule_id] = self._pool.submit(self._run_probe, rule)

    def status(self, rule: MonitoredProcess) -> Dict[str, Any]:
        process = self._owned_process(rule.rule_id, rule.executable)
        external = self._externally_running(rule) if process is None else False
        result = {
            "name": rule.name, "enabled": rule.enabled,
            "process_state": "owned" if process else ("external" if external else "stopped"),
            "pid": process.pid if process else None,
            "last_output": self._last_documents.get(rule.rule_id),
            "last_error": self._last_errors.get(rule.rule_id),
            "probe_running": bool(self._futures.get(rule.rule_id) and not self._futures[rule.rule_id].done()),
        }
        if self.history is not None:
            result["statistics"] = self.history.monitor_summary(rule)
            result["log_file"] = result["statistics"]["log_file"]
        return result

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
