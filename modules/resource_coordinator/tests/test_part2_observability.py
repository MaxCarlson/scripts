from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from resource_coordinator.core.durable_state import RequestPhase, StateCodec
from resource_coordinator.core.events import EventDispatcher
from resource_coordinator.core.inference_status import build_inference_status
from resource_coordinator.core.leases import LeaseManager
from resource_coordinator.core.recovery_assessment import assess_recovery
from resource_coordinator.monitors.lmstudio_activity import UnavailableLMStudioActivityObserver


class _Maintenance:
    def status(self):
        return {"state": "idle"}


class _Service:
    def __init__(self, path: Path):
        self.system = SimpleNamespace(
            config=SimpleNamespace(service=SimpleNamespace(state_persistence_path=str(path))),
            lease_mgr=LeaseManager(event_dispatcher=EventDispatcher()),
        )
        self.maintenance_manager = _Maintenance()
        self.runtime_identity = {"runtime_revision": "fixture"}
        self.state = SimpleNamespace(value="ready")
        self.is_ready = True


def test_quiescent_is_scoped_and_not_physical_idle_proof(tmp_path):
    journal = tmp_path / "state.json"
    StateCodec.initialize(journal)
    service = _Service(journal)
    status = build_inference_status(service)
    assert status["classification"] == "quiescent"
    assert status["coverage"] == "partial"
    assert status["physical_gpu_idle_proven"] is False
    assert "external_runtime_activity_unobserved" in status["reason_codes"]


def test_unconfigured_durable_journal_makes_inference_state_unavailable():
    service = _Service(Path("unused"))
    service.system.config.service.state_persistence_path = ""

    status = build_inference_status(service)

    assert status["classification"] == "unavailable"
    assert status["coverage"] == "unknown"
    assert status["physical_gpu_idle_proven"] is False


def test_unresolved_forwarded_request_is_uncertain_and_requires_operator(tmp_path):
    journal = tmp_path / "state.json"
    StateCodec.initialize(journal)
    StateCodec.record_request_phase(
        journal, "uncertain-request", "gpu.inference", RequestPhase.UNCERTAIN,
        model="qwen-test", details={"failure_kind": "read_timeout", "prompt": "private"},
    )
    service = _Service(journal)
    status = build_inference_status(service)
    assessment = assess_recovery(service, inference_status=status)
    assert status["classification"] == "uncertain"
    assert status["unresolved_requests"][0]["request_id"] == "uncertain-request"
    assert "prompt" not in str(status)
    assert assessment["classification"] == "operator_required"
    assert assessment["automatic_recovery_available"] is False


def test_healthy_state_is_no_action_not_auto_recoverable(tmp_path):
    journal = tmp_path / "state.json"
    StateCodec.initialize(journal)
    result = assess_recovery(_Service(journal))
    assert result["classification"] == "no_action_required"
    assert result["exit_code"] == 0
    assert result["automatic_recovery_available"] is False


def test_recovery_assessment_blocks_on_interrupted_upgrade_receipt(monkeypatch, tmp_path):
    import json

    from resource_coordinator import installation

    receipt = tmp_path / "upgrade-receipt.json"
    receipt.write_text(json.dumps({"phase": "RECOVERY_REQUIRED", "operation_id": "upgrade-123",
                                   "token": "must-not-leak"}), encoding="utf-8")
    monkeypatch.setattr(installation.InstallationPaths, "discover", lambda: SimpleNamespace(upgrade_receipt=receipt))
    journal = tmp_path / "state.json"
    StateCodec.initialize(journal)

    result = assess_recovery(_Service(journal))

    assert result["classification"] == "blocked"
    assert "upgrade_recovery_required" in result["reason_codes"]
    assert result["upgrade_receipt"]["operation_id"] == "upgrade-123"
    assert "must-not-leak" not in json.dumps(result)


def test_oversized_upgrade_receipt_is_not_loaded(monkeypatch, tmp_path):
    from resource_coordinator import installation
    from resource_coordinator.core.recovery_assessment import read_upgrade_receipt_summary

    receipt = tmp_path / "upgrade-receipt.json"
    receipt.write_bytes(b" " * (1024 * 1024 + 1))
    monkeypatch.setattr(installation.InstallationPaths, "discover", lambda: SimpleNamespace(upgrade_receipt=receipt))

    assert read_upgrade_receipt_summary() == {"status": "unavailable", "reason_code": "upgrade_receipt_oversized"}


def test_unavailable_lmstudio_observer_never_probes_runtime():
    import asyncio

    result = asyncio.run(UnavailableLMStudioActivityObserver().observe(runtime_identity={"instance": "fixture"}))
    assert result["status"] == "unavailable"
    assert result["reason_code"] == "no_wake_probe_not_qualified"
