#!/usr/bin/env python3
"""Read-only NVML and Windows process identity probe for H4 WDDM qualification."""

__version__ = "0.1.0"

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence


NVML_VALUE_NOT_AVAILABLE = (1 << 64) - 1
NVML_STATUS = {
    0: "available",
    2: "invalid_argument",
    3: "unsupported",
    4: "permission_denied",
    7: "retry_size_changed",
    10: "timeout",
    13: "unavailable",
    15: "gpu_lost",
}
PROCESS_APIS = (
    "nvmlDeviceGetComputeRunningProcesses_v3",
    "nvmlDeviceGetGraphicsRunningProcesses_v3",
)
MAX_PROCESS_ROWS = 4096
MAX_ENUMERATION_ATTEMPTS = 3


class NvmlProcessInfo(ctypes.Structure):
    """NVML nvmlProcessInfo_t layout: pid, memory, GPU instance and compute instance."""

    _fields_ = [
        ("pid", ctypes.c_uint),
        ("usedGpuMemory", ctypes.c_ulonglong),
        ("gpuInstanceId", ctypes.c_uint),
        ("computeInstanceId", ctypes.c_uint),
    ]


def classify_nvml_status(code: int) -> str:
    """Map stable NVML return codes without treating permission or API errors as empty results."""
    return NVML_STATUS.get(int(code), "query_failed")


def classify_gpu_memory(value: int) -> Dict[str, Any]:
    """Keep WDDM's documented unavailable memory sentinel separate from process presence."""
    value = int(value)
    if value == NVML_VALUE_NOT_AVAILABLE:
        return {"status": "unavailable_under_wddm", "bytes": None}
    if value < 0:
        return {"status": "malformed", "bytes": None}
    return {"status": "available", "bytes": value}


def classify_process_identity(pid: int, expected_create_time: Optional[float],
                              observed_create_time: Optional[float], *, tolerance: float = 0.01) -> str:
    """Compare PID creation-time identity; PID alone never proves the same process."""
    if expected_create_time is None or observed_create_time is None:
        return "identity_unverifiable"
    try:
        expected = float(expected_create_time)
        observed = float(observed_create_time)
    except (TypeError, ValueError, OverflowError):
        return "identity_unverifiable"
    if pid <= 0 or not (expected >= 0 and observed >= 0):
        return "identity_unverifiable"
    return "same_identity" if abs(expected - observed) <= tolerance else "pid_reused_or_mismatched"


def compare_expected_process(expected: Dict[str, Any], rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare an independently recorded expected process with NVML PID rows and OS identity."""
    try:
        expected_pid = int(expected["pid"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"status": "invalid_expected_identity"}
    matches = [row for row in rows if row.get("pid") == expected_pid]
    if not matches:
        return {"status": "pid_absent_from_sampled_nvml_apis", "pid": expected_pid}
    observed = next((row for row in matches if row.get("identity_status") == "available"), matches[0])
    identity_status = classify_process_identity(
        expected_pid, expected.get("create_time"), observed.get("create_time")
    )
    expected_executable = expected.get("executable")
    observed_executable = observed.get("executable")
    if expected_executable and observed_executable:
        path_matches = os.path.normcase(os.path.normpath(str(expected_executable))) == os.path.normcase(
            os.path.normpath(str(observed_executable))
        )
    else:
        path_matches = None
    if identity_status != "same_identity":
        status = identity_status
    elif path_matches is False:
        status = "executable_mismatch"
    elif path_matches is None:
        status = "executable_unverifiable"
    else:
        status = "same_identity"
    return {
        "status": status,
        "pid": expected_pid,
        "sources": sorted({source for row in matches for source in row.get("sources", [])}),
        "observed_create_time": observed.get("create_time"),
        "observed_executable": observed_executable,
    }


def compare_device_identity(expected_uuid: str, expected_driver: Optional[str],
                             snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Report GPU UUID and optional driver consistency without implying process completeness."""
    observed_uuid = snapshot.get("gpu_uuid_observed")
    observed_driver = snapshot.get("driver_version")
    uuid_matches = isinstance(observed_uuid, str) and observed_uuid.casefold() == expected_uuid.casefold()
    driver_matches = None if expected_driver is None or observed_driver is None else observed_driver == expected_driver
    if not uuid_matches:
        status = "gpu_uuid_mismatch_or_unavailable"
    elif driver_matches is False:
        status = "driver_changed"
    elif driver_matches is None:
        status = "driver_identity_unavailable"
    else:
        status = "same_device_identity"
    return {"status": status, "gpu_uuid_matches": uuid_matches, "driver_matches": driver_matches,
            "observed_driver_version": observed_driver}


def _load_nvml() -> Any:
    if os.name != "nt":
        raise OSError("This qualification probe requires Windows NVML")
    return ctypes.WinDLL("nvml.dll")


def _set_signature(function: Any, arguments: Sequence[Any], result: Any = ctypes.c_int) -> Any:
    function.argtypes = list(arguments)
    function.restype = result
    return function


def _text_query(library: Any, name: str, *arguments: Any) -> str:
    function = _set_signature(getattr(library, name), [*arguments, ctypes.c_char_p, ctypes.c_uint])
    buffer = ctypes.create_string_buffer(128)
    code = function(*arguments, buffer, len(buffer))
    if code != 0:
        raise OSError(f"{name} returned NVML code {code} ({classify_nvml_status(code)})")
    return buffer.value.decode("utf-8", errors="replace")


def _query_process_api(library: Any, handle: Any, name: str) -> Dict[str, Any]:
    function = getattr(library, name, None)
    if function is None:
        return {"status": "unsupported", "reason": "function_not_exported", "rows": []}
    _set_signature(
        function,
        [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(NvmlProcessInfo)],
    )
    count = ctypes.c_uint(0)
    code = int(function(handle, ctypes.byref(count), None))
    if code not in (0, 7):
        return {"status": classify_nvml_status(code), "nvml_code": code, "rows": []}
    for _ in range(MAX_ENUMERATION_ATTEMPTS):
        needed = int(count.value)
        if needed > MAX_PROCESS_ROWS:
            return {"status": "capacity_exceeded", "count": needed, "rows": []}
        if needed == 0 and code == 0:
            return {"status": "available", "count": 0, "rows": []}
        capacity = max(needed, 1)
        buffer_type = NvmlProcessInfo * capacity
        buffer = buffer_type()
        count = ctypes.c_uint(capacity)
        code = int(function(handle, ctypes.byref(count), buffer))
        if code == 0:
            rows = []
            for item in buffer[: min(int(count.value), capacity)]:
                memory = classify_gpu_memory(item.usedGpuMemory)
                rows.append({
                    "pid": int(item.pid),
                    "used_gpu_memory": memory,
                    "gpu_instance_id": int(item.gpuInstanceId),
                    "compute_instance_id": int(item.computeInstanceId),
                })
            return {"status": "available", "count": len(rows), "rows": rows}
        if code != 7:
            return {"status": classify_nvml_status(code), "nvml_code": code, "rows": []}
    return {"status": "enumeration_raced", "nvml_code": int(code), "rows": []}


def _process_identity(pid: int) -> Dict[str, Any]:
    try:
        import psutil
    except ImportError:
        return {"identity_status": "psutil_unavailable"}
    try:
        process = psutil.Process(pid)
        create_time = float(process.create_time())
        executable = str(Path(process.exe()).resolve(strict=True))
        return {
            "identity_status": "available",
            "create_time": create_time,
            "executable": executable,
            "process_name": process.name(),
        }
    except psutil.NoSuchProcess:
        return {"identity_status": "pid_gone_during_inspection"}
    except psutil.AccessDenied:
        return {"identity_status": "access_denied"}
    except (OSError, psutil.Error, ValueError):
        return {"identity_status": "identity_unverifiable"}


def capture_snapshot(gpu_uuid: str, *, expected_process: Optional[Dict[str, Any]] = None,
                     library: Any = None) -> Dict[str, Any]:
    """Capture one read-only sample from both NVML process APIs and the OS process table."""
    library = library or _load_nvml()
    init = _set_signature(getattr(library, "nvmlInit_v2"), [])
    shutdown = _set_signature(getattr(library, "nvmlShutdown"), [])
    handle_by_uuid = _set_signature(
        getattr(library, "nvmlDeviceGetHandleByUUID"), [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
    )
    if init() != 0:
        raise OSError("nvmlInit_v2 failed")
    try:
        handle = ctypes.c_void_p()
        result = int(handle_by_uuid(gpu_uuid.encode("ascii"), ctypes.byref(handle)))
        if result != 0:
            raise OSError(f"NVML GPU UUID lookup failed: {result} ({classify_nvml_status(result)})")
        actual_uuid = _text_query(library, "nvmlDeviceGetUUID", handle)
        driver = _text_query(library, "nvmlSystemGetDriverVersion")
        apis: Dict[str, Any] = {}
        rows_by_pid: Dict[int, Dict[str, Any]] = {}
        for api_name in PROCESS_APIS:
            result_data = _query_process_api(library, handle, api_name)
            source = "compute" if "Compute" in api_name else "graphics"
            apis[source] = {key: value for key, value in result_data.items() if key != "rows"}
            for row in result_data.get("rows", []):
                pid = int(row["pid"])
                merged = rows_by_pid.setdefault(pid, {"pid": pid, "sources": []})
                merged["sources"].append(source)
                merged[source] = {key: value for key, value in row.items() if key != "pid"}
        process_rows = []
        for pid, row in sorted(rows_by_pid.items()):
            row.update(_process_identity(pid))
            row["sources"] = sorted(set(row["sources"]))
            process_rows.append(row)
        expected_result = None
        if expected_process is not None:
            expected_os_identity = _process_identity(int(expected_process.get("pid", 0)))
            expected_result = compare_expected_process(expected_process, process_rows)
            expected_result["os_identity_before_or_after_sample"] = expected_os_identity
        return {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "gpu_uuid_requested": gpu_uuid,
            "gpu_uuid_observed": actual_uuid,
            "gpu_identity_match": actual_uuid.casefold() == gpu_uuid.casefold(),
            "driver_version": driver,
            "process_api_coverage": "sampled_compute_and_graphics_apis_only",
            "inventory_completeness": "not_established_by_sampling",
            "apis": apis,
            "processes": process_rows,
            "expected_process_comparison": expected_result,
        }
    finally:
        shutdown()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-one", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("-u", "--gpu-uuid", required=True, help="Expected GPU UUID; no index fallback is used")
    parser.add_argument("-n", "--snapshots", type=int, default=3, help="Bounded sample count (1-6)")
    parser.add_argument("-i", "--interval-seconds", type=float, default=3.0,
                        help="Delay between samples (0-10 seconds)")
    parser.add_argument("-T", "--timeout-seconds", type=float, default=8.0,
                        help="Per-snapshot worker timeout (1-15 seconds)")
    parser.add_argument("-p", "--expected-pid", type=int, help="Optional PID independently recorded by RC")
    parser.add_argument("-t", "--expected-create-time", type=float,
                        help="Creation time for --expected-pid from independent process evidence")
    parser.add_argument("-e", "--expected-executable", help="Expected exact executable path for --expected-pid")
    parser.add_argument("-o", "--output", type=Path, help="Absolute JSON output path; defaults to stdout")
    return parser


def _capture_bounded(gpu_uuid: str, expected: Optional[Dict[str, Any]], timeout: float) -> Dict[str, Any]:
    """Run a potentially blocked vendor call in a disposable helper with a hard timeout."""
    command = [sys.executable, str(Path(__file__).resolve()), "--capture-one", "--gpu-uuid", gpu_uuid]
    if expected is not None:
        command.extend(["--expected-pid", str(expected["pid"]),
                        "--expected-create-time", str(expected["create_time"])])
        if expected.get("executable"):
            command.extend(["--expected-executable", str(expected["executable"])])
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:500]
        raise OSError(f"NVML helper exited {result.returncode}: {detail}")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError("NVML helper returned a non-object snapshot")
    return value


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.capture_one:
        try:
            expected = None
            if args.expected_pid is not None and args.expected_create_time is not None:
                expected = {"pid": args.expected_pid, "create_time": args.expected_create_time,
                            "executable": args.expected_executable}
            sys.stdout.write(json.dumps(capture_snapshot(args.gpu_uuid, expected_process=expected), sort_keys=True))
            return 0
        except (OSError, ValueError, ctypes.ArgumentError, AttributeError) as exc:
            print(f"read-only NVML probe unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 3
    if not 1 <= args.snapshots <= 6 or not 0 <= args.interval_seconds <= 10 or not 1 <= args.timeout_seconds <= 15:
        print("snapshots must be 1..6, interval-seconds 0..10, and timeout-seconds 1..15", file=sys.stderr)
        return 2
    has_expected = args.expected_pid is not None
    if has_expected != (args.expected_create_time is not None):
        print("--expected-pid and --expected-create-time must be supplied together", file=sys.stderr)
        return 2
    if args.output is not None and not args.output.is_absolute():
        print("--output must be an absolute path", file=sys.stderr)
        return 2
    expected = None
    if has_expected:
        if args.expected_pid <= 0:
            print("--expected-pid must be positive", file=sys.stderr)
            return 2
        expected = {"pid": args.expected_pid, "create_time": args.expected_create_time,
                    "executable": args.expected_executable}
    try:
        snapshots = []
        for index in range(args.snapshots):
            snapshots.append(_capture_bounded(args.gpu_uuid, expected, args.timeout_seconds))
            if index + 1 < args.snapshots:
                time.sleep(args.interval_seconds)
        baseline_driver = snapshots[0].get("driver_version") if snapshots else None
        for snapshot in snapshots:
            snapshot["device_identity_comparison"] = compare_device_identity(
                args.gpu_uuid, baseline_driver, snapshot
            )
        result = {"schema_version": 1, "tool_version": __version__, "snapshots": snapshots}
        encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8")
        else:
            sys.stdout.write(encoded)
        return 0
    except (OSError, ValueError, ctypes.ArgumentError, subprocess.TimeoutExpired, AttributeError) as exc:
        print(f"read-only NVML probe unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
