import ctypes
import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).parents[1] / "tools" / "h4_qualification" / "wddm_probe.py"
SPEC = importlib.util.spec_from_file_location("h4_wddm_probe", MODULE_PATH)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class FakeFunction:
    def __init__(self, call):
        self.call = call

    def __call__(self, *args):
        return self.call(*args)


def test_wddm_memory_unavailable_does_not_imply_process_absence():
    memory = probe.classify_gpu_memory(probe.NVML_VALUE_NOT_AVAILABLE)
    assert memory == {"status": "unavailable_under_wddm", "bytes": None}

    row = {"pid": 1234, "sources": ["graphics"], "identity_status": "available",
           "create_time": 100.0, "executable": r"C:\test\app.exe"}
    expected = {"pid": 1234, "create_time": 100.0, "executable": r"C:\test\app.exe"}
    comparison = probe.compare_expected_process(expected, [row])
    assert comparison["status"] == "same_identity"
    assert comparison["sources"] == ["graphics"]


def test_expected_process_sources_are_reported_from_merged_nvml_record():
    expected = {"pid": 1234, "create_time": 100.0, "executable": r"C:\test\app.exe"}
    row = {"pid": 1234, "sources": ["compute", "graphics"], "identity_status": "available",
           "create_time": 100.0, "executable": r"C:\test\app.exe"}
    assert probe.compare_expected_process(expected, [row])["sources"] == ["compute", "graphics"]


def test_compute_and_graphics_pid_reuse_is_rejected():
    expected = {"pid": 1234, "create_time": 100.0, "executable": r"C:\test\app.exe"}
    row = {"pid": 1234, "source": "compute", "identity_status": "available",
           "create_time": 200.0, "executable": r"C:\test\app.exe"}
    assert probe.compare_expected_process(expected, [row])["status"] == "pid_reused_or_mismatched"


def test_expected_executable_mismatch_is_not_accepted():
    expected = {"pid": 1234, "create_time": 100.0, "executable": r"C:\expected\miner.exe"}
    row = {"pid": 1234, "source": "graphics", "identity_status": "available",
           "create_time": 100.0, "executable": r"C:\other\miner.exe"}
    assert probe.compare_expected_process(expected, [row])["status"] == "executable_mismatch"


def test_nvml_no_permission_is_not_empty_inventory():
    api = "nvmlDeviceGetComputeRunningProcesses_v3"
    result = probe._query_process_api(SimpleNamespace(**{api: FakeFunction(lambda *_: 4)}), object(), api)
    assert result["status"] == "permission_denied"
    assert result["rows"] == []


def test_process_api_enumerates_pid_and_preserves_wddm_memory_status():
    def call(_handle, count_pointer, rows_pointer):
        count = count_pointer._obj
        if rows_pointer is None:
            count.value = 1
            return 7
        rows = ctypes.cast(rows_pointer, ctypes.POINTER(probe.NvmlProcessInfo))
        rows[0].pid = 1234
        rows[0].usedGpuMemory = probe.NVML_VALUE_NOT_AVAILABLE
        rows[0].gpuInstanceId = 0
        rows[0].computeInstanceId = 0
        count.value = 1
        return 0

    api = "nvmlDeviceGetGraphicsRunningProcesses_v3"
    result = probe._query_process_api(SimpleNamespace(**{api: FakeFunction(call)}), object(), api)
    assert result["status"] == "available"
    assert result["count"] == 1
    assert result["rows"][0]["pid"] == 1234
    assert result["rows"][0]["used_gpu_memory"]["status"] == "unavailable_under_wddm"


def test_missing_process_api_is_classified_unsupported():
    result = probe._query_process_api(object(), object(), "nvmlDeviceGetGraphicsRunningProcesses_v3")
    assert result == {"status": "unsupported", "reason": "function_not_exported", "rows": []}


def test_nvml_gpu_lost_and_permission_errors_remain_distinct():
    assert probe.classify_nvml_status(4) == "permission_denied"
    assert probe.classify_nvml_status(15) == "gpu_lost"
    assert probe.classify_nvml_status(3) == "unsupported"


def test_device_uuid_and_driver_mismatch_are_explicit():
    sample = {"gpu_uuid_observed": "GPU-other", "driver_version": "621.14"}
    assert probe.compare_device_identity("GPU-target", "621.14", sample)["status"] == \
        "gpu_uuid_mismatch_or_unavailable"
    sample["gpu_uuid_observed"] = "GPU-target"
    sample["driver_version"] = "622.00"
    assert probe.compare_device_identity("GPU-target", "621.14", sample)["status"] == "driver_changed"


def test_vendor_helper_timeout_propagates_for_fail_closed_classification(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("nvml-helper", 1)

    monkeypatch.setattr(probe.subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        probe._capture_bounded("GPU-test", None, 1)


def test_cli_supports_short_and_long_flags():
    parser = probe.build_parser()
    short = parser.parse_args(["-u", "GPU-test", "-n", "2", "-i", "0", "-T", "3", "-p", "123",
                               "-t", "1.5", "-e", r"C:\miner.exe"])
    long = parser.parse_args(["--gpu-uuid", "GPU-test", "--snapshots", "2", "--interval-seconds", "0",
                              "--timeout-seconds", "3", "--expected-pid", "123", "--expected-create-time",
                              "1.5", "--expected-executable", r"C:\miner.exe"])
    assert short.gpu_uuid == long.gpu_uuid == "GPU-test"
    assert short.expected_pid == long.expected_pid == 123
