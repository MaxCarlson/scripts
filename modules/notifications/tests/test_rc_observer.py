"""Tests for Resource Coordinator polling observer, contract parsing, incident mapping, and isolation (Phase 05)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from notifications.integrations.resource_coordinator import (
    DEFAULT_COORDINATOR_STATUS_URL,
    RCObservation,
    ResourceCoordinatorObserver,
)
from notifications.models import EventEnvelopeV1
from notifications.publisher import Publisher
from notifications.storage import StorageEngine


@pytest.fixture
def storage(tmp_path: Path) -> StorageEngine:
    engine = StorageEngine(tmp_path / "test_events.db")
    engine.migrate()
    return engine


@pytest.fixture
def publisher(storage: StorageEngine) -> Publisher:
    return Publisher(storage)


# ── Synthetic Status Fixtures ────────────────────────────────────────────────

MODERN_RECOVERY_REQUIRED_PAYLOAD: Dict[str, Any] = {
    "service": {"status": "ok", "version": "0.1.2"},
    "gpu_inference": {
        "recovery": {
            "required": True,
            "inhibition": {
                "resource": "gpu.inference",
                "holder_id": "coord-test-1",
                "reason": "upstream_read_timeout",
                "inhibited_at": 1700000000,
                "details": {"operation_type": "model_load"},
            },
            "requests": [
                {
                    "request_id": "coord-req-1",
                    "resource": "gpu.inference",
                    "phase": "uncertain",
                    "model": "qwen2.5-coder",
                    "details": {"outcome": "execution_uncertain"},
                }
            ],
            "journal_status": "available",
            "recommendation": "Verify upstream idle, then recover with explicit reason.",
        },
        "inhibition": {"reason": "upstream_read_timeout"},
    },
    "miner": {"state": "restart_inhibited"},
}

MODERN_CLEARED_PAYLOAD: Dict[str, Any] = {
    "service": {"status": "ok", "version": "0.1.2"},
    "gpu_inference": {
        "recovery": {
            "required": False,
            "inhibition": None,
            "requests": [],
            "journal_status": "available",
            "recommendation": "Normal operation.",
        },
        "inhibition": None,
    },
    "miner": {"state": "running"},
}

LEGACY_INHIBITED_PAYLOAD: Dict[str, Any] = {
    "service": {"status": "ok", "version": "0.1.0"},
    "gpu_inference": {
        "inhibition": {"reason": "legacy_timeout_hold"},
    },
    "miner": {"state": "paused"},
}

LEGACY_HEALTHY_PAYLOAD: Dict[str, Any] = {
    "service": {"status": "ok", "version": "0.1.0"},
    "gpu_inference": {
        "inhibition": None,
    },
    "miner": {"state": "running"},
}


# ── Security & Loopback Isolation Tests ──────────────────────────────────────

def test_observer_loopback_url_validation() -> None:
    """Observer strictly enforces loopback binding, rejecting arbitrary remote URLs."""
    # Valid loopback targets
    for valid_url in [
        "http://127.0.0.1:1235/_coordinator/status",
        "http://localhost:1235/_coordinator/status",
        "https://127.0.0.1:8443/status",
    ]:
        obs = ResourceCoordinatorObserver(status_url=valid_url)
        assert obs.status_url == valid_url

    # Prohibited non-loopback targets
    for bad_url in [
        "http://192.168.1.50:1235/_coordinator/status",
        "http://example.com/status",
        "ftp://127.0.0.1:1235/status",
        "http://0.0.0.0:1235/status",
    ]:
        with pytest.raises(ValueError, match="prohibited|scheme"):
            ResourceCoordinatorObserver(status_url=bad_url)


def test_no_resource_coordinator_imports() -> None:
    """Notifications observer must not import or depend on Resource Coordinator code."""
    import sys

    # Assert modules/resource_coordinator was not imported
    loaded_rc_modules = [m for m in sys.modules if m.startswith("resource_coordinator")]
    assert len(loaded_rc_modules) == 0, f"Leaked RC modules in memory: {loaded_rc_modules}"


# ── Contract Parsing Tests ───────────────────────────────────────────────────

def test_parse_modern_contract_recovery_required() -> None:
    """Modern contract correctly parses required recovery, journal, and inhibition reason."""
    obs_engine = ResourceCoordinatorObserver()
    obs = obs_engine.parse_status_payload(MODERN_RECOVERY_REQUIRED_PAYLOAD, observed_at="2026-11-11T12:00:00Z")

    assert obs.status == "available"
    assert obs.contract_version == "modern_v1"
    assert obs.has_recovery_contract is True
    assert obs.recovery_required is True
    assert obs.inhibition_active is True
    assert obs.inhibition_reason == "upstream_read_timeout"
    assert obs.journal_status == "available"
    assert obs.miner_state == "restart_inhibited"
    assert obs.details["unresolved_requests_count"] == 1


def test_parse_modern_contract_cleared() -> None:
    """Modern contract correctly recognizes authoritative cleared status."""
    obs_engine = ResourceCoordinatorObserver()
    obs = obs_engine.parse_status_payload(MODERN_CLEARED_PAYLOAD, observed_at="2026-11-11T12:00:00Z")

    assert obs.status == "available"
    assert obs.contract_version == "modern_v1"
    assert obs.has_recovery_contract is True
    assert obs.recovery_required is False
    assert obs.inhibition_active is False
    assert obs.journal_status == "available"
    assert obs.miner_state == "running"


def test_parse_legacy_contract_uncertainty_preservation() -> None:
    """Legacy contract without recovery fields records recovery_required as None (unknown)."""
    obs_engine = ResourceCoordinatorObserver()
    obs = obs_engine.parse_status_payload(LEGACY_INHIBITED_PAYLOAD, observed_at="2026-11-11T12:00:00Z")

    assert obs.status == "available"
    assert obs.contract_version == "legacy"
    assert obs.has_recovery_contract is False
    # MANDATORY RULE B4: Missing recovery fields must not be assumed required=False
    assert obs.recovery_required is None
    assert obs.inhibition_active is True
    assert obs.inhibition_reason == "legacy_timeout_hold"
    assert obs.journal_status is None


def test_parse_malformed_and_unknown_fields() -> None:
    """Malformed or payload with unknown forward-compatible fields handled gracefully."""
    obs_engine = ResourceCoordinatorObserver()

    # Forward-compatible extra fields
    extra_payload = {
        **MODERN_RECOVERY_REQUIRED_PAYLOAD,
        "future_field_v3": "some_telemetry",
        "unknown_extra_metric": 42,
    }
    obs_extra = obs_engine.parse_status_payload(extra_payload)
    assert obs_extra.status == "available"
    assert obs_extra.contract_version == "modern_v1"

    # Non-dictionary payload
    obs_bad = obs_engine.parse_status_payload(["not", "a", "dict"])
    assert obs_bad.status == "degraded"
    assert obs_bad.contract_version == "unknown"


# ── Incident Lifecycle & Deduplication Tests ────────────────────────────────

def test_incident_creation_and_storm_suppression(storage: StorageEngine, publisher: Publisher) -> None:
    """First recovery-required observation creates an incident; repeated polls do not storm."""
    mock_transport = MagicMock(return_value=MODERN_RECOVERY_REQUIRED_PAYLOAD)
    observer = ResourceCoordinatorObserver(
        storage=storage,
        publisher=publisher,
        transport_fn=mock_transport,
    )

    # 1. First poll: incident opened
    obs1 = observer.poll_once()
    assert obs1.recovery_required is True

    incidents = storage.list_incidents()
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc.incident_key == "gpu_inference_recovery"
    assert inc.source == "resource_coordinator"
    assert inc.severity == "critical"
    assert inc.status == "open"

    pending_outbox_1 = len(storage.list_pending_outbox())
    assert pending_outbox_1 >= 1

    # 2. Second poll with identical state: no new outbox items (storm suppression)
    obs2 = observer.poll_once()
    assert obs2.recovery_required is True

    incidents_2 = storage.list_incidents()
    assert len(incidents_2) == 1
    pending_outbox_2 = len(storage.list_pending_outbox())
    assert pending_outbox_2 == pending_outbox_1  # No duplicate notifications!


def test_coordinator_outage_preserves_safety_holds(storage: StorageEngine, publisher: Publisher) -> None:
    """Coordinator service unavailability never resolves active safety incidents."""
    # First: active recovery hold observed
    transport = MagicMock(return_value=MODERN_RECOVERY_REQUIRED_PAYLOAD)
    observer = ResourceCoordinatorObserver(
        storage=storage,
        publisher=publisher,
        transport_fn=transport,
    )
    observer.poll_once()

    inc = storage.get_incident(EventEnvelopeV1(
        schema_version=1,
        event_id="00000000-0000-0000-0000-000000000000",
        source="resource_coordinator",
        kind="recovery_required",
        incident_key="gpu_inference_recovery",
        severity="critical",
        occurred_at="2026-11-11T12:00:00Z",
        summary="dummy",
    ).incident_id)
    assert inc is not None
    assert inc.status == "open"

    # Second: Coordinator goes down (connection refused)
    transport.side_effect = ConnectionRefusedError("Connection refused on port 1235")
    obs_down = observer.poll_once()
    assert obs_down.status == "unavailable"

    # Verify:
    # 1. Separate availability incident opened
    inc_avail = storage.list_incidents(status="open")
    keys = {i.incident_key for i in inc_avail}
    assert "rc_service_unavailable" in keys

    # 2. Safety hold is STILL OPEN (MANDATORY RULE B4)
    safety_inc = [i for i in inc_avail if i.incident_key == "gpu_inference_recovery"][0]
    assert safety_inc.status == "open"


def test_coordinator_recovery_clears_only_service_incident(storage: StorageEngine, publisher: Publisher) -> None:
    """Coordinator returning online resolves rc_service_unavailable, keeping safety holds."""
    transport = MagicMock(return_value=MODERN_RECOVERY_REQUIRED_PAYLOAD)
    observer = ResourceCoordinatorObserver(
        storage=storage,
        publisher=publisher,
        transport_fn=transport,
    )

    # 1. Observe recovery required
    observer.poll_once()

    # 2. Coordinator goes offline
    transport.side_effect = TimeoutError("Poll timed out")
    observer.poll_once()

    # 3. Coordinator comes back online, STILL reporting recovery required
    transport.side_effect = None
    transport.return_value = MODERN_RECOVERY_REQUIRED_PAYLOAD
    observer.poll_once()

    open_incidents = storage.list_incidents(status="open")
    resolved_incidents = storage.list_incidents(status="resolved")

    # Service incident resolved
    assert any(i.incident_key == "rc_service_unavailable" for i in resolved_incidents)
    # Safety hold remains open
    assert any(i.incident_key == "gpu_inference_recovery" for i in open_incidents)


def test_authoritative_hold_clearing_resolves_safety_incident(storage: StorageEngine, publisher: Publisher) -> None:
    """Authoritative response with required=False cleanly resolves the safety hold."""
    transport = MagicMock(return_value=MODERN_RECOVERY_REQUIRED_PAYLOAD)
    observer = ResourceCoordinatorObserver(
        storage=storage,
        publisher=publisher,
        transport_fn=transport,
    )

    # 1. Open safety hold
    observer.poll_once()
    assert len(storage.list_incidents(status="open")) == 1

    # 2. Authoritative clear received
    transport.return_value = MODERN_CLEARED_PAYLOAD
    observer.poll_once()

    # Safety hold is now resolved
    open_incidents = storage.list_incidents(status="open")
    assert len(open_incidents) == 0
    resolved = storage.list_incidents(status="resolved")
    assert any(i.incident_key == "gpu_inference_recovery" for i in resolved)


def test_legacy_missing_fields_never_causes_false_resolution(storage: StorageEngine, publisher: Publisher) -> None:
    """Switching to legacy status with missing fields preserves existing unresolved hold."""
    transport = MagicMock(return_value=MODERN_RECOVERY_REQUIRED_PAYLOAD)
    observer = ResourceCoordinatorObserver(
        storage=storage,
        publisher=publisher,
        transport_fn=transport,
    )

    # 1. Open safety hold under modern contract
    observer.poll_once()

    # 2. Next response is legacy without recovery fields (e.g. coordinator restarted older version)
    # It has inhibition=None, but has_recovery_contract=False!
    legacy_empty = {"service": {"status": "ok"}, "gpu_inference": {}}
    transport.return_value = legacy_empty
    obs = observer.poll_once()
    assert obs.has_recovery_contract is False
    assert obs.recovery_required is None

    # Hold must remain OPEN!
    open_incidents = storage.list_incidents(status="open")
    assert any(i.incident_key == "gpu_inference_recovery" for i in open_incidents)


def test_normalized_observation_persistence(storage: StorageEngine) -> None:
    """Observations are transactionally persisted to rc_observations in SQLite."""
    observer = ResourceCoordinatorObserver(storage=storage)
    obs = observer.parse_status_payload(MODERN_RECOVERY_REQUIRED_PAYLOAD)

    row_id = storage.save_rc_observation(obs.to_dict())
    assert row_id > 0

    latest = storage.get_latest_rc_observation()
    assert latest is not None
    assert latest["contract_version"] == "modern_v1"
    assert latest["has_recovery_contract"] is True
    assert latest["recovery_required"] is True
    assert latest["inhibition_reason"] == "upstream_read_timeout"
    assert latest["journal_status"] == "available"


# ── Phase 05 Stabilization & Correctness Regression Tests ────────────────────

def test_missing_and_null_recovery_required_field_remains_unknown(storage: StorageEngine) -> None:
    """Missing, null, or non-boolean required fields must remain unknown (None)."""
    observer = ResourceCoordinatorObserver(storage=storage)

    # 1. Missing 'required' field entirely in recovery
    payload_missing_req = {
        "service": {"status": "ok"},
        "gpu_inference": {
            "recovery": {
                "inhibition": {"reason": "timeout"},
                "requests": [],
            }
        },
    }
    obs1 = observer.parse_status_payload(payload_missing_req)
    assert obs1.has_recovery_contract is True
    assert obs1.recovery_required is None  # Must remain unknown!
    assert obs1.inhibition_active is True

    # 2. Null 'required' field
    payload_null_req = {
        "service": {"status": "ok"},
        "gpu_inference": {
            "recovery": {
                "required": None,
                "inhibition": None,
            }
        },
    }
    obs2 = observer.parse_status_payload(payload_null_req)
    assert obs2.has_recovery_contract is True
    assert obs2.recovery_required is None  # Null must not be converted to False!

    # 3. String / invalid type 'required' field
    payload_str_req = {
        "service": {"status": "ok"},
        "gpu_inference": {
            "recovery": {
                "required": "true",
                "inhibition": None,
            }
        },
    }
    obs3 = observer.parse_status_payload(payload_str_req)
    assert obs3.recovery_required is None
    assert obs3.status == "degraded"


def test_contradictory_recovery_required_false_with_active_inhibition(
    storage: StorageEngine, publisher: Publisher
) -> None:
    """Contradictory status (required=False but inhibition active) must not clear safety hold."""
    observer = ResourceCoordinatorObserver(storage=storage, publisher=publisher)

    # First open a valid safety hold
    transport = MagicMock(return_value=MODERN_RECOVERY_REQUIRED_PAYLOAD)
    observer._transport_fn = transport
    observer.poll_once()
    assert len(storage.list_incidents(status="open")) == 1

    # Now observe contradictory payload: required=False, but inhibition.active=True
    contradictory_payload = {
        "service": {"status": "ok"},
        "gpu_inference": {
            "recovery": {
                "required": False,
                "inhibition": {"reason": "model load failed", "active": True},
                "requests": [],
            }
        },
    }
    obs = observer.parse_status_payload(contradictory_payload)
    assert obs.status == "degraded"
    assert obs.recovery_required is None  # Overridden to unknown due to contradiction!
    assert obs.inhibition_active is True

    # Reconciling this must NEVER resolve the open safety incident
    transport.return_value = contradictory_payload
    observer.poll_once()
    open_incidents = storage.list_incidents(status="open")
    assert any(i.incident_key == "gpu_inference_recovery" for i in open_incidents)


def test_durable_deduplication_across_fresh_observer_instances(storage: StorageEngine) -> None:
    """Durable state prevents duplicate notifications and preserved operator acks across restarts."""
    transport = MagicMock(return_value=MODERN_RECOVERY_REQUIRED_PAYLOAD)

    # 1. Instance 1 polls and creates open incident
    pub1 = Publisher(storage, default_providers=["fake_provider"])
    obs1 = ResourceCoordinatorObserver(storage=storage, publisher=pub1, transport_fn=transport)
    obs1.poll_once()

    incidents = storage.list_incidents(status="open")
    assert len(incidents) == 1
    inc_id = incidents[0].incident_id

    # 1 outbox item was queued
    outbox_initial = storage.list_pending_outbox()
    assert len(outbox_initial) == 1

    # 2. Operator acknowledges incident
    pub1.lifecycle.acknowledge_incident(inc_id, actor="operator-1", reason="Operator investigating")
    inc_acked = storage.get_incident(inc_id)
    assert inc_acked is not None
    assert inc_acked.status == "acknowledged"

    # 3. Instance 2 (fresh observer instance simulating process restart) polls SAME payload
    pub2 = Publisher(storage, default_providers=["fake_provider"])
    obs2 = ResourceCoordinatorObserver(storage=storage, publisher=pub2, transport_fn=transport)
    obs2.poll_once()

    # Invariant A: Status MUST REMAIN "acknowledged" (not wiped out to "open")
    inc_after = storage.get_incident(inc_id)
    assert inc_after is not None
    assert inc_after.status == "acknowledged"

    # Invariant B: No new outbox notification items enqueued
    outbox_after = storage.list_pending_outbox()
    assert len(outbox_after) == 1  # Still exactly 1, no duplicate queued!


def test_provider_selection_routes_to_actual_providers(storage: StorageEngine) -> None:
    """Observer routes outbox events to registered delivery provider IDs and never 'default'."""
    transport = MagicMock(return_value=MODERN_RECOVERY_REQUIRED_PAYLOAD)

    # Explicitly specify fake_provider
    pub = Publisher(storage, default_providers=["fake_provider"])
    observer = ResourceCoordinatorObserver(storage=storage, publisher=pub, transport_fn=transport)
    observer.poll_once()

    outbox = storage.list_pending_outbox()
    assert len(outbox) == 1
    assert outbox[0].provider_id == "fake_provider"
    assert outbox[0].provider_id != "default"


def test_observer_bounds_transport_and_rejects_arbitrary_paths() -> None:
    """Observer rejects non-canonical paths and external hosts."""
    # Arbitrary path rejected
    with pytest.raises(ValueError, match="Prohibited status path"):
        ResourceCoordinatorObserver(status_url="http://127.0.0.1:1235/admin/restart")

    with pytest.raises(ValueError, match="Prohibited status path"):
        ResourceCoordinatorObserver(status_url="http://127.0.0.1:1235/api/v1/delete")

    # Canonical paths accepted
    obs1 = ResourceCoordinatorObserver(status_url="http://127.0.0.1:1235/_coordinator/status")
    assert obs1.status_url == "http://127.0.0.1:1235/_coordinator/status"

    obs2 = ResourceCoordinatorObserver(status_url="http://127.0.0.1:1235/status")
    assert obs2.status_url == "http://127.0.0.1:1235/status"


def test_prune_old_rc_observations(storage: StorageEngine) -> None:
    """Observations are pruned based on age and maximum record limits."""
    # Seed 5 observations
    for i in range(5):
        ts = f"2026-11-0{i+1}T12:00:00Z"
        storage.save_rc_observation({
            "observed_at": ts,
            "status": "available",
            "contract_version": "v1",
            "has_recovery_contract": True,
            "recovery_required": False,
            "inhibition_active": False,
        })

    # Prune keeping max 2 records
    deleted = storage.prune_rc_observations(max_age_days=30, max_records=2)
    assert deleted == 3

    # Latest record is still preserved
    latest = storage.get_latest_rc_observation()
    assert latest is not None
    assert latest["observed_at"] == "2026-11-05T12:00:00Z"


def test_coordinator_task_management_dry_run() -> None:
    """Task management functions support dry-run and status checks without executing mutations."""
    from notifications.integrations.resource_coordinator import (
        get_coordinator_task_status,
        install_coordinator_task,
        uninstall_coordinator_task,
    )

    stat = get_coordinator_task_status()
    assert stat["ok"] is True
    assert "task_installed" in stat

    inst = install_coordinator_task(apply=False, interval_minutes=3)
    assert inst["ok"] is True
    assert inst["dry_run"] is True
    assert inst["interval_minutes"] == 3
    assert inst["requires_apply"] is True

    uninst = uninstall_coordinator_task(apply=False)
    assert uninst["ok"] is True
    assert uninst["dry_run"] is True
    assert uninst["requires_apply"] is True
