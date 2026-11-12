from __future__ import annotations

from resource_coordinator.core.restoration import (
    NvmlGpuObserver,
    TrustedRestorationVerifier,
    evaluate_gpu_restoration,
    verify_process_termination,
)


def observation(*, gpu_uuid="GPU-test", driver="555.1", at=100.0, values=None):
    return {
        "schema_version": 1,
        "observed_at": at,
        "gpu_uuid": gpu_uuid,
        "pci_bus_id": "00000000:01:00.0",
        "driver_version": driver,
        "values": values or {
            "power_limit_mw": {"status": "available", "value": 300000},
            "graphics_clock_offset_mhz": {"status": "available", "value": 0},
            "memory_clock_offset_mhz": {"status": "available", "value": 0},
        },
    }


def test_gpu_restoration_accepts_matching_identity_driver_and_exact_settings():
    scope = {"mode": "power_offsets", "dimensions": [
        "power_limit_mw", "graphics_clock_offset_mhz", "memory_clock_offset_mhz"
    ]}
    result = evaluate_gpu_restoration(
        scope,
        observation(at=190.0),
        observation(at=200.0),
        expected_gpu_uuid="GPU-test",
        max_age_seconds=30,
        now=205.0,
    )
    assert result.verified is True
    assert result.reason_code == "verified"
    assert result.comparisons["memory_clock_offset_mhz"]["match"] is True


def test_gpu_restoration_fails_closed_on_unsupported_dimension():
    scope = {"mode": "offsets", "dimensions": ["graphics_clock_offset_mhz", "memory_clock_offset_mhz"]}
    after = observation(at=200.0, values={
        "graphics_clock_offset_mhz": {"status": "unsupported", "reason": "not_supported"},
        "memory_clock_offset_mhz": {"status": "available", "value": 0},
    })
    result = evaluate_gpu_restoration(scope, observation(at=190.0), after,
        expected_gpu_uuid="GPU-test", max_age_seconds=30, now=205.0)
    assert result.verified is False
    assert result.reason_code == "setting_unavailable"


def test_gpu_restoration_rejects_identity_driver_stale_and_fixed_clock_scope():
    scope = {"mode": "power", "dimensions": ["power_limit_mw"]}
    baseline = observation(at=190.0)
    assert evaluate_gpu_restoration(scope, baseline, observation(gpu_uuid="GPU-other", at=200),
        expected_gpu_uuid="GPU-test", max_age_seconds=30, now=205).reason_code == "gpu_identity_mismatch"
    assert evaluate_gpu_restoration(scope, baseline, observation(driver="556.0", at=200),
        expected_gpu_uuid="GPU-test", max_age_seconds=30, now=205).reason_code == "driver_changed"
    assert evaluate_gpu_restoration(scope, baseline, observation(at=201),
        expected_gpu_uuid="GPU-test", max_age_seconds=30, now=250).reason_code == "baseline_stale"
    assert evaluate_gpu_restoration({"mode": "fixed_clocks", "dimensions": ["locked_clocks"]},
        baseline, observation(at=200), expected_gpu_uuid="GPU-test", max_age_seconds=30,
        now=205).reason_code == "unsupported_tuning_mode"


def test_gpu_restoration_rejects_setting_change_and_malformed_scope():
    scope = {"mode": "power", "dimensions": ["power_limit_mw"]}
    changed = observation(at=200, values={"power_limit_mw": {"status": "available", "value": 299000}})
    result = evaluate_gpu_restoration(
        scope, observation(at=190), changed, expected_gpu_uuid="GPU-test", max_age_seconds=30, now=205
    )
    assert result.verified is False
    assert result.reason_code == "setting_mismatch"
    assert evaluate_gpu_restoration(
        {"mode": "power", "dimensions": ["locked_clocks"]}, observation(at=190), observation(at=200),
        expected_gpu_uuid="GPU-test", max_age_seconds=30, now=205
    ).reason_code == "invalid_tuning_scope"
    assert evaluate_gpu_restoration(
        {"mode": "power_offsets", "dimensions": ["power_limit_mw"]}, observation(at=190),
        observation(at=200), expected_gpu_uuid="GPU-test", max_age_seconds=30, now=205
    ).reason_code == "invalid_tuning_scope"


def test_process_termination_requires_complete_inventory_and_no_known_miner():
    registered = [{"pid": 123, "create_time": 10.0, "executable_path": r"C:\miners\krig.exe",
                   "executable_name": "krig.exe"}]
    result = verify_process_termination(registered, [], known_executables=["krig.exe"], complete=True)
    assert result.verified is True
    survivor = [{"pid": 123, "create_time": 10.0, "executable_path": r"C:\miners\krig.exe",
                 "executable_name": "krig.exe"}]
    assert verify_process_termination(registered, survivor, known_executables=["krig.exe"],
        complete=True).reason_code == "registered_process_running"
    recycled = [{"pid": 123, "create_time": 20.0, "executable_path": r"C:\other\app.exe",
                 "executable_name": "app.exe"}]
    assert verify_process_termination(registered, recycled, known_executables=["krig.exe"],
        complete=True).verified is True
    assert verify_process_termination(registered, [], known_executables=["krig.exe"],
        complete=False).reason_code == "process_inventory_incomplete"


def test_process_termination_rejects_unregistered_known_miner_and_missing_registration():
    known = [{"pid": 789, "create_time": 30.0, "executable_path": r"C:\miners\krig.exe",
              "executable_name": "krig.exe"}]
    assert verify_process_termination([], [], known_executables=["krig.exe"],
        complete=True).reason_code == "process_registration_missing"
    assert verify_process_termination([], known, known_executables=["krig.exe"],
        complete=True).reason_code == "unregistered_known_miner_running"


class FakeNvmlFunction:
    def __call__(self, handle_type, output):
        output._obj.clockOffsetMHz = 0
        return 0


class FakeNvml:
    NVML_SUCCESS = 0
    NVML_PSTATE_0 = 0
    NVML_CLOCK_GRAPHICS = 0
    NVML_CLOCK_MEM = 2

    def __init__(self, *, offset_api=True):
        self.calls = []
        self.nvmlLib = type("Lib", (), {})()
        if offset_api:
            self.nvmlLib.nvmlDeviceGetClockOffsets = FakeNvmlFunction()

    def nvmlInit(self):
        self.calls.append("init")

    def nvmlShutdown(self):
        self.calls.append("shutdown")

    def nvmlDeviceGetHandleByUUID(self, _uuid):
        return object()

    def nvmlDeviceGetUUID(self, _handle):
        return b"GPU-test"

    def nvmlDeviceGetPciInfo(self, _handle):
        return type("Pci", (), {"busId": b"00000000:01:00.0"})()

    def nvmlSystemGetDriverVersion(self):
        return b"555.1"

    def nvmlDeviceGetPowerManagementLimit(self, _handle):
        return 300000

    def nvmlDeviceGetComputeRunningProcesses(self, _handle):
        self.calls.append("compute_processes")
        return []

    def nvmlDeviceGetGraphicsRunningProcesses(self, _handle):
        self.calls.append("graphics_processes")
        return []

    def _nvmlCheckReturn(self, code):
        raise RuntimeError(f"NVML error {code}")


def test_nvml_observer_reads_expected_fields_and_never_mutates_gpu():
    nvml = FakeNvml()
    result = NvmlGpuObserver(nvml_module=nvml, clock=lambda: 200.0).observe(
        "GPU-test", ["power_limit_mw", "graphics_clock_offset_mhz", "memory_clock_offset_mhz"]
    )
    assert result["gpu_uuid"] == "GPU-test"
    assert result["values"]["power_limit_mw"] == {"status": "available", "value": 300000}
    assert result["values"]["graphics_clock_offset_mhz"] == {"status": "available", "value": 0}
    assert result["values"]["memory_clock_offset_mhz"] == {"status": "available", "value": 0}
    assert result["gpu_processes"] == {"status": "available", "pids": []}
    assert nvml.calls == ["init", "compute_processes", "graphics_processes", "shutdown"]


def test_nvml_observer_classifies_missing_clock_offset_api_as_unsupported():
    nvml = FakeNvml(offset_api=False)
    result = NvmlGpuObserver(nvml_module=nvml).observe("GPU-test", ["graphics_clock_offset_mhz"])
    assert result["values"]["graphics_clock_offset_mhz"] == {
        "status": "unsupported", "reason": "api_unavailable"
    }


def test_legacy_maintenance_record_without_operation_bound_baseline_cannot_auto_release():
    verifier = TrustedRestorationVerifier(
        gpu_uuid="GPU-test", known_miner_executables=["krig.exe"],
        gpu_process_attribution_confirmed=True,
    )
    result = verifier.verify({"state": "recovery_required", "operation_id": "legacy-op"}, {})
    assert result.verified is False
    assert result.reason_code == "trusted_baseline_or_scope_missing"
