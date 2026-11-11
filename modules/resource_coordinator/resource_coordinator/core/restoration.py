"""Read-only evidence for gated GPU maintenance restoration."""

from __future__ import annotations

import ctypes
import importlib
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence

import psutil


SETTING_DIMENSIONS = {
    "power_limit_mw",
    "graphics_clock_offset_mhz",
    "memory_clock_offset_mhz",
}
_SUPPORTED_MODES = {
    "power": {"power_limit_mw"},
    "offsets": {"graphics_clock_offset_mhz", "memory_clock_offset_mhz"},
    "power_offsets": SETTING_DIMENSIONS,
}


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    reason_code: str
    gpu_uuid: Optional[str] = None
    comparisons: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    process_termination: Dict[str, Any] = field(default_factory=dict)
    observed_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verified": self.verified,
            "reason_code": self.reason_code,
            "gpu_uuid": self.gpu_uuid,
            "comparisons": self.comparisons,
            "process_termination": self.process_termination,
            "observed_at": self.observed_at,
        }


class GpuObserver(Protocol):
    def observe(self, gpu_uuid: str, dimensions: Sequence[str]) -> Dict[str, Any]: ...


class ProcessObserver(Protocol):
    def inspect(self, pid: int, known_executables: Sequence[str]) -> Dict[str, Any]: ...
    def inspect_any(self, pid: int) -> Dict[str, Any]: ...
    def inventory(self, known_executables: Sequence[str]) -> Dict[str, Any]: ...


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def evaluate_gpu_restoration(
    scope: Dict[str, Any],
    baseline: Dict[str, Any],
    current: Dict[str, Any],
    *,
    expected_gpu_uuid: str,
    max_age_seconds: float,
    now: Optional[float] = None,
) -> VerificationResult:
    """Compare exact independent NVML values. Unknown dimensions are never accepted."""
    timestamp = time.time() if now is None else now
    mode = scope.get("mode") if isinstance(scope, dict) else None
    dimensions = scope.get("dimensions") if isinstance(scope, dict) else None
    allowed = _SUPPORTED_MODES.get(mode)
    if mode == "fixed_clocks" or allowed is None:
        return VerificationResult(False, "unsupported_tuning_mode")
    if not isinstance(dimensions, list) or not dimensions or len(dimensions) > 3:
        return VerificationResult(False, "invalid_tuning_scope")
    if len(set(dimensions)) != len(dimensions) or set(dimensions) != allowed:
        return VerificationResult(False, "invalid_tuning_scope")
    for index, sample in enumerate((baseline, current)):
        if not isinstance(sample, dict) or sample.get("schema_version") != 1:
            return VerificationResult(False, "baseline_invalid")
        if not _finite_number(sample.get("observed_at")):
            return VerificationResult(False, "observation_invalid")
        age = timestamp - float(sample["observed_at"])
        if age < -5.0:
            return VerificationResult(False, "observation_from_future")
        if index == 1 and age > max_age_seconds:
            return VerificationResult(False, "baseline_stale")
        if sample.get("gpu_uuid") != expected_gpu_uuid:
            return VerificationResult(False, "gpu_identity_mismatch")
    if baseline.get("gpu_uuid") != current.get("gpu_uuid"):
        return VerificationResult(False, "gpu_identity_mismatch")
    if float(baseline["observed_at"]) > float(current["observed_at"]):
        return VerificationResult(False, "baseline_invalid")
    if baseline.get("pci_bus_id") != current.get("pci_bus_id"):
        return VerificationResult(False, "gpu_identity_mismatch")
    if not baseline.get("driver_version") or baseline.get("driver_version") != current.get("driver_version"):
        return VerificationResult(False, "driver_changed")
    before_values = baseline.get("values")
    after_values = current.get("values")
    if not isinstance(before_values, dict) or not isinstance(after_values, dict):
        return VerificationResult(False, "observation_invalid")
    comparisons: Dict[str, Dict[str, Any]] = {}
    for dimension in dimensions:
        before = before_values.get(dimension)
        after = after_values.get(dimension)
        if not all(isinstance(value, dict) and value.get("status") == "available"
                   and _finite_number(value.get("value")) for value in (before, after)):
            comparisons[dimension] = {"match": False, "status": "unavailable"}
            return VerificationResult(False, "setting_unavailable", current.get("gpu_uuid"), comparisons,
                                      observed_at=current["observed_at"])
        # Power is in integer milliwatts and clock offsets in integer MHz; exact read-back is required.
        match = before["value"] == after["value"]
        comparisons[dimension] = {
            "match": match,
            "baseline": before["value"],
            "current": after["value"],
            "unit": "mW" if dimension == "power_limit_mw" else "MHz",
        }
        if not match:
            return VerificationResult(False, "setting_mismatch", current.get("gpu_uuid"), comparisons,
                                      observed_at=current["observed_at"])
    return VerificationResult(True, "verified", current.get("gpu_uuid"), comparisons,
                              observed_at=current["observed_at"])


def verify_process_termination(
    registered: Sequence[Dict[str, Any]],
    processes: Sequence[Dict[str, Any]],
    *,
    known_executables: Sequence[str],
    complete: bool,
) -> VerificationResult:
    """Require registered identities to be absent and no known miner to remain."""
    if not complete:
        return VerificationResult(False, "process_inventory_incomplete")
    if not isinstance(registered, (list, tuple)) or any(
        not isinstance(item, dict) or type(item.get("pid")) is not int or item["pid"] <= 0
        or not _finite_number(item.get("create_time"))
        or not isinstance(item.get("executable_path"), str)
        or not isinstance(item.get("executable_name"), str)
        for item in registered
    ):
        return VerificationResult(False, "process_registration_invalid")
    allowed = {Path(name).name.casefold() for name in known_executables}
    identities = {int(item.get("pid", -1)): item for item in registered}
    for process in processes:
        name = str(process.get("executable_name", "")).casefold()
        if name not in allowed:
            continue
        expected = identities.get(process.get("pid"))
        if expected and process.get("create_time") == expected.get("create_time") \
                and os.path.normcase(str(process.get("executable_path", ""))) == os.path.normcase(
                    str(expected.get("executable_path", ""))):
            return VerificationResult(False, "registered_process_running",
                                      process_termination={"registered_processes": len(registered)})
        return VerificationResult(False, "unregistered_known_miner_running",
                                  process_termination={"registered_processes": len(registered)})
    if not registered:
        return VerificationResult(False, "process_registration_missing")
    return VerificationResult(True, "verified", process_termination={"registered_processes": len(registered)})


class NvmlGpuObserver:
    """Bounded caller-owned NVML reads; this adapter never issues set commands."""

    def __init__(self, nvml_module: Any = None, clock=time.time) -> None:
        self._nvml = nvml_module
        self.clock = clock

    def _module(self) -> Any:
        if self._nvml is None:
            try:
                self._nvml = importlib.import_module("pynvml")
            except ImportError as exc:
                raise RuntimeError("NVML Python bindings are not installed") from exc
        return self._nvml

    @staticmethod
    def _text(value: Any) -> str:
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)

    @staticmethod
    def _clock_offset(nvml: Any, handle: Any, clock_type: int) -> int:
        """Use NVML's versioned read API where the driver exports it."""
        library = getattr(nvml, "nvmlLib", None)
        function = getattr(library, "nvmlDeviceGetClockOffsets", None) if library is not None else None
        if function is None:
            raise NotImplementedError("nvmlDeviceGetClockOffsets is unavailable in the loaded NVML library")

        class ClockOffsetV1(ctypes.Structure):
            _fields_ = [("version", ctypes.c_uint), ("type", ctypes.c_uint), ("pstate", ctypes.c_uint),
                        ("clockOffsetMHz", ctypes.c_int), ("minClockOffsetMHz", ctypes.c_int),
                        ("maxClockOffsetMHz", ctypes.c_int)]

        value = ClockOffsetV1()
        value.version = ctypes.sizeof(ClockOffsetV1) | (1 << 24)
        value.type = clock_type
        value.pstate = getattr(nvml, "NVML_PSTATE_0", 0)
        function.argtypes = [type(handle), ctypes.POINTER(ClockOffsetV1)]
        function.restype = ctypes.c_int
        result = function(handle, ctypes.byref(value))
        if result != getattr(nvml, "NVML_SUCCESS", 0):
            nvml._nvmlCheckReturn(result)
        return int(value.clockOffsetMHz)

    def observe(self, gpu_uuid: str, dimensions: Sequence[str]) -> Dict[str, Any]:
        nvml = self._module()
        nvml.nvmlInit()
        try:
            handle = nvml.nvmlDeviceGetHandleByUUID(gpu_uuid.encode("ascii"))
            actual_uuid = self._text(nvml.nvmlDeviceGetUUID(handle))
            pci = nvml.nvmlDeviceGetPciInfo(handle)
            bus_id = self._text(getattr(pci, "busId", getattr(pci, "busIdLegacy", "")))
            driver = self._text(nvml.nvmlSystemGetDriverVersion())
            values: Dict[str, Dict[str, Any]] = {}
            for dimension in dimensions:
                try:
                    if dimension == "power_limit_mw":
                        value = int(nvml.nvmlDeviceGetPowerManagementLimit(handle))
                    elif dimension == "graphics_clock_offset_mhz":
                        value = self._clock_offset(nvml, handle, getattr(nvml, "NVML_CLOCK_GRAPHICS", 0))
                    elif dimension == "memory_clock_offset_mhz":
                        value = self._clock_offset(nvml, handle, getattr(nvml, "NVML_CLOCK_MEM", 2))
                    else:
                        values[dimension] = {"status": "unsupported", "reason": "unknown_dimension"}
                        continue
                    values[dimension] = {"status": "available", "value": value}
                except NotImplementedError:
                    values[dimension] = {"status": "unsupported", "reason": "api_unavailable"}
                except Exception as exc:
                    if "NotSupported" in type(exc).__name__ or "FunctionNotFound" in type(exc).__name__:
                        values[dimension] = {"status": "unsupported", "reason": "driver_not_supported"}
                    else:
                        raise
            process_api_names = (
                "nvmlDeviceGetComputeRunningProcesses",
                "nvmlDeviceGetGraphicsRunningProcesses",
            )
            if all(callable(getattr(nvml, name, None)) for name in process_api_names):
                gpu_pids = set()
                try:
                    for name in process_api_names:
                        gpu_pids.update(int(item.pid) for item in getattr(nvml, name)(handle))
                    gpu_processes = {"status": "available", "pids": sorted(gpu_pids)}
                except Exception as exc:
                    reason = "not_supported" if "NotSupported" in type(exc).__name__ else "query_failed"
                    gpu_processes = {"status": "unavailable", "reason": reason}
            else:
                gpu_processes = {"status": "unavailable", "reason": "process_api_unavailable"}
            return {
                "schema_version": 1,
                "observed_at": self.clock(),
                "gpu_uuid": actual_uuid,
                "pci_bus_id": bus_id,
                "driver_version": driver,
                "values": values,
                "gpu_processes": gpu_processes,
            }
        finally:
            nvml.nvmlShutdown()


class PsutilProcessObserver:
    """Read exact registered process identities and a conservative known-miner inventory."""

    def inspect(self, pid: int, known_executables: Sequence[str]) -> Dict[str, Any]:
        identity = self.inspect_any(pid)
        if identity["executable_name"].casefold() not in {
            Path(item).name.casefold() for item in known_executables
        }:
            raise ValueError("Registered executable is not an allowed miner")
        return identity

    @staticmethod
    def inspect_any(pid: int) -> Dict[str, Any]:
        process = psutil.Process(pid)
        executable = str(Path(process.exe()).resolve(strict=True))
        name = Path(executable).name
        return {"pid": pid, "create_time": float(process.create_time()),
                "executable_path": executable, "executable_name": name}

    def inventory(self, known_executables: Sequence[str]) -> Dict[str, Any]:
        allowed = {Path(name).name.casefold() for name in known_executables}
        rows: List[Dict[str, Any]] = []
        complete = True
        for process in psutil.process_iter(attrs=["pid", "name", "exe", "create_time"]):
            try:
                info = process.info
                name = info.get("name")
                executable = info.get("exe")
                if not name and not executable:
                    complete = False
                    continue
                executable_name = Path(executable or name).name
                if executable_name.casefold() in allowed:
                    if not executable or info.get("create_time") is None:
                        complete = False
                    else:
                        rows.append({"pid": int(info["pid"]), "create_time": float(info["create_time"]),
                                     "executable_path": str(Path(executable).resolve(strict=True)),
                                     "executable_name": executable_name})
            except psutil.NoSuchProcess:
                continue
            except (psutil.AccessDenied, OSError, ValueError):
                complete = False
        return {"complete": complete, "processes": rows}


class TrustedRestorationVerifier:
    """Independent GPU and external-process verification used by maintenance releases."""

    def __init__(self, *, gpu_uuid: str, known_miner_executables: Sequence[str],
                 max_age_seconds: float = 30.0, gpu_observer: Optional[GpuObserver] = None,
                 process_observer: Optional[ProcessObserver] = None,
                 allowed_gpu_processes: Sequence[str] = (),
                 gpu_process_attribution_confirmed: bool = False,
                 allowed_dimensions: Optional[Sequence[str]] = None, clock=time.time) -> None:
        self.gpu_uuid = gpu_uuid
        self.known_miner_executables = tuple(known_miner_executables)
        self.max_age_seconds = max_age_seconds
        self.allowed_dimensions = frozenset(allowed_dimensions or SETTING_DIMENSIONS)
        self.allowed_gpu_processes = frozenset(Path(item).name.casefold() for item in allowed_gpu_processes)
        self.gpu_process_attribution_confirmed = gpu_process_attribution_confirmed is True
        self.clock = clock
        self.gpu_observer = gpu_observer or NvmlGpuObserver(clock=clock)
        self.process_observer = process_observer or PsutilProcessObserver()

    def validate_scope(self, scope: Any) -> bool:
        if not isinstance(scope, dict) or scope.get("mode") == "fixed_clocks":
            return False
        allowed = _SUPPORTED_MODES.get(scope.get("mode"))
        dimensions = scope.get("dimensions")
        return bool(allowed and isinstance(dimensions, list) and dimensions
                    and len(set(dimensions)) == len(dimensions)
                    and set(dimensions) == allowed
                    and all(item in self.allowed_dimensions for item in dimensions))

    def capture_baseline(self, scope: Dict[str, Any]) -> Dict[str, Any]:
        if not self.gpu_process_attribution_confirmed:
            raise RuntimeError("GPU process-attribution capability has not been accepted for this platform")
        if not self.validate_scope(scope):
            raise ValueError("Unsupported or invalid maintenance tuning scope")
        observation = self.gpu_observer.observe(self.gpu_uuid, scope["dimensions"])
        attribution = observation.get("gpu_processes")
        if not isinstance(attribution, dict) or attribution.get("status") != "available" \
                or not isinstance(attribution.get("pids"), list):
            raise RuntimeError("GPU process attribution is unavailable")
        identities = []
        for pid in attribution["pids"]:
            identity = self.process_observer.inspect_any(int(pid))
            if identity["executable_name"].casefold() not in self.allowed_gpu_processes:
                raise RuntimeError("An unapproved GPU process is active before maintenance")
            identities.append(identity)
        observation["gpu_processes"] = {"status": "available", "identities": identities}
        return observation

    def preflight(self, scope: Dict[str, Any]) -> None:
        """Prove the configured observer can read required dimensions before RC stops its miner."""
        if not self.gpu_process_attribution_confirmed:
            raise RuntimeError("GPU process-attribution capability has not been accepted for this platform")
        if not self.validate_scope(scope):
            raise ValueError("Unsupported or invalid maintenance tuning scope")
        observation = self.gpu_observer.observe(self.gpu_uuid, scope["dimensions"])
        if observation.get("gpu_uuid") != self.gpu_uuid:
            raise RuntimeError("Configured GPU identity could not be observed")
        values = observation.get("values", {})
        if any(not isinstance(values.get(item), dict) or values[item].get("status") != "available"
               for item in scope["dimensions"]):
            raise RuntimeError("A required GPU setting cannot be independently observed")
        attribution = observation.get("gpu_processes")
        if not isinstance(attribution, dict) or attribution.get("status") != "available" \
                or not isinstance(attribution.get("pids"), list):
            raise RuntimeError("GPU process attribution is unavailable")

    def inspect_process(self, pid: int) -> Dict[str, Any]:
        return self.process_observer.inspect(pid, self.known_miner_executables)

    def verify(self, record: Dict[str, Any], _client_evidence: Dict[str, Any]) -> VerificationResult:
        if not self.gpu_process_attribution_confirmed:
            return VerificationResult(False, "gpu_process_attribution_not_accepted")
        scope = record.get("tuning_scope")
        baseline = record.get("gpu_baseline")
        if not self.validate_scope(scope) or not isinstance(baseline, dict):
            return VerificationResult(False, "trusted_baseline_or_scope_missing")
        if baseline.get("operation_id") != record.get("operation_id") \
                or baseline.get("observed_at", 0) < record.get("requested_at", float("inf")):
            return VerificationResult(False, "baseline_not_bound_to_operation")
        baseline_processes = baseline.get("gpu_processes")
        if not isinstance(baseline_processes, dict) or baseline_processes.get("status") != "available" \
                or not isinstance(baseline_processes.get("identities"), list):
            return VerificationResult(False, "baseline_gpu_process_attribution_missing")
        if any(
            not isinstance(item, dict)
            or not isinstance(item.get("executable_name"), str)
            or item["executable_name"].casefold() not in self.allowed_gpu_processes
            for item in baseline_processes["identities"]
        ):
            return VerificationResult(False, "baseline_contains_unapproved_gpu_process")
        current = self.gpu_observer.observe(self.gpu_uuid, scope["dimensions"])
        attribution = current.get("gpu_processes")
        if not isinstance(attribution, dict) or attribution.get("status") != "available" \
                or not isinstance(attribution.get("pids"), list):
            return VerificationResult(False, "gpu_process_attribution_unavailable",
                                      observed_at=current.get("observed_at"))
        current_gpu_identities = []
        try:
            for pid in attribution["pids"]:
                identity = self.process_observer.inspect_any(int(pid))
                if identity["executable_name"].casefold() not in self.allowed_gpu_processes:
                    return VerificationResult(False, "unapproved_gpu_process",
                                              observed_at=current.get("observed_at"))
                current_gpu_identities.append(identity)
        except Exception:
            return VerificationResult(False, "gpu_process_identity_unavailable",
                                      observed_at=current.get("observed_at"))
        current["gpu_processes"] = {"status": "available", "identities": current_gpu_identities}
        gpu_result = evaluate_gpu_restoration(
            scope, baseline, current, expected_gpu_uuid=self.gpu_uuid,
            max_age_seconds=self.max_age_seconds, now=self.clock(),
        )
        if not gpu_result.verified:
            return gpu_result
        inventory = self.process_observer.inventory(self.known_miner_executables)
        process_result = verify_process_termination(
            record.get("registered_processes", []), inventory.get("processes", []),
            known_executables=self.known_miner_executables,
            complete=inventory.get("complete") is True,
        )
        if not process_result.verified:
            return process_result
        return VerificationResult(True, "verified", gpu_uuid=gpu_result.gpu_uuid,
                                  comparisons=gpu_result.comparisons,
                                  process_termination=process_result.process_termination,
                                  observed_at=gpu_result.observed_at)

    def __call__(self, record: Dict[str, Any], evidence: Dict[str, Any]) -> bool:
        return self.verify(record, evidence).verified
