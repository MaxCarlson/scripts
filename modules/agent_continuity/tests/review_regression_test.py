"""Independent M1 review regression tests for persistence, concurrency, and cross-spool ingestion."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agent_continuity.errors import ContinuityError, ErrorCode
from agent_continuity.events import append_event, discover_spool_roots, read_spool_events
from agent_continuity.models import EventEnvelope, EventType
from agent_continuity.service import ContinuityService


def test_oversized_and_unsupported_schema_events_are_reported_as_issues(tmp_path: Path) -> None:
    home = tmp_path / "state"
    svc = ContinuityService(home_dir=home)
    svc.add_workflow(slug="alpha", title="Alpha", apply=True)

    env_dir = home / "events" / "env_bad"
    env_dir.mkdir(parents=True, exist_ok=True)
    # 1. Oversized file (> max_event_bytes)
    oversized = env_dir / "001_oversized.json"
    oversized.write_text("{" + (" " * 2048) + "}", encoding="utf-8")

    # 2. Unsupported event_schema_version
    bad_ver = env_dir / "002_bad_ver.json"
    bad_ver.write_text(
        json.dumps(
            {
                "event_id": "evt_bad_ver",
                "event_schema_version": 99,
                "event_type": "workflow.registered",
                "environment_id": "env_bad",
                "source_timestamp": "2026-11-19T10:00:00Z",
                "observed_timestamp": "2026-11-19T10:00:00Z",
                "payload": {},
            }
        ),
        encoding="utf-8",
    )

    # 3. Empty event_id
    empty_id = env_dir / "003_empty_id.json"
    empty_id.write_text(
        json.dumps(
            {
                "event_id": "   ",
                "event_schema_version": 1,
                "event_type": "workflow.registered",
                "environment_id": "env_bad",
                "source_timestamp": "2026-11-19T10:00:00Z",
                "observed_timestamp": "2026-11-19T10:00:00Z",
                "payload": {},
            }
        ),
        encoding="utf-8",
    )

    scan = read_spool_events(
        discover_spool_roots(home),
        optional_roots={home / "events"},
        max_event_bytes=1024,
    )
    reasons = [issue.reason for issue in scan.issues]
    assert len(scan.issues) == 3
    assert any("Oversized event file" in r for r in reasons)
    assert any("Unsupported event_schema_version" in r for r in reasons)
    assert any("non-empty strings" in r for r in reasons)


def test_failed_rebuild_preserves_last_valid_sqlite_index(tmp_path: Path) -> None:
    home = tmp_path / "state"
    svc = ContinuityService(home_dir=home)
    wf_id = svc.add_workflow(slug="safe", title="Safe", apply=True).details["workflow_id"]
    svc.link_session(
        workflow_identifier=wf_id,
        provider="codex",
        native_session_id="ses-safe",
        environment_selector="windows",
        apply=True,
    )

    # Inject a schema-valid event that violates SQLite FK constraints during replay (missing workflow)
    bad_evt = EventEnvelope(
        event_id="evt_fk_fail",
        event_schema_version=1,
        event_type=EventType.ASSOCIATION_CREATED.value,
        provider="codex",
        environment_id="env_win_manual",
        native_session_id="ses-orphan",
        source_timestamp="2099-01-01T00:00:00Z",
        observed_timestamp="2099-01-01T00:00:00Z",
        source_adapter_version="0.1.0",
        payload={
            "association_id": "assoc_bad_fk",
            "workflow_id": "wf_nonexistent",
            "evidence_level": "confirmed",
        },
    )
    bad_path = append_event(home, bad_evt)

    with pytest.raises(ContinuityError) as exc_info:
        svc.rebuild_index(apply=True)
    assert exc_info.value.code == ErrorCode.MATERIALIZER_FAILED

    # Staging temp files must be cleaned up
    assert list(home.glob(".index.sqlite.rebuild.*.tmp")) == []

    # Remove the poison event and verify the last valid index was never destroyed
    bad_path.unlink()
    found = svc.find_sessions(workflow_identifier=wf_id)
    assert len(found["sessions"]) == 1
    assert found["sessions"][0]["session"]["native_session_id"] == "ses-safe"


def test_concurrent_event_writers_do_not_corrupt_spool(tmp_path: Path) -> None:
    home = tmp_path / "state"
    svc = ContinuityService(home_dir=home)
    wf_id = svc.add_workflow(slug="concurrent", title="Concurrent", apply=True).details["workflow_id"]

    def _emit(i: int) -> Path:
        ev = EventEnvelope(
            event_id=f"evt_conc_{i:03d}",
            event_schema_version=1,
            event_type=EventType.SESSION_REGISTERED.value,
            provider="codex",
            environment_id="env_conc",
            native_session_id=f"ses-{i:03d}",
            source_timestamp=f"2026-11-19T12:00:{i:02d}Z",
            observed_timestamp=f"2026-11-19T12:00:{i:02d}Z",
            source_adapter_version="0.1.0",
            payload={"first_observed_at": f"2026-11-19T12:00:{i:02d}Z"},
        )
        return append_event(home, ev)

    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(_emit, range(32)))

    assert len(paths) == 32
    res = svc.materializer.sync_from_spools()
    assert res.issues == []
    assert res.ingested_count == 32
    assert len(svc.materializer.list_sessions(environment_id="env_conc")) == 32
    assert svc.find_sessions(workflow_identifier=wf_id)["sessions"] == []


def test_inaccessible_and_valid_extra_spool_dirs_handling(tmp_path: Path) -> None:
    win_home = tmp_path / "win_home"
    wsl_spool = tmp_path / "wsl_home" / "events"
    missing_spool = tmp_path / "missing_wsl_share" / "events"

    win_home.mkdir(parents=True)
    (win_home / "config.json").write_text(
        json.dumps({"extra_spool_dirs": [str(wsl_spool), str(missing_spool)]}),
        encoding="utf-8",
    )

    svc = ContinuityService(home_dir=win_home)
    wf_id = svc.add_workflow(slug="cross", title="Cross OS", apply=True).details["workflow_id"]

    # Simulate WSL2 emitting a session + association event into wsl_spool
    wsl_home = tmp_path / "wsl_home"
    append_event(
        wsl_home,
        EventEnvelope(
            event_id="evt_wsl_ses_1",
            event_schema_version=1,
            event_type=EventType.SESSION_REGISTERED.value,
            provider="agy",
            environment_id="env_wsl_ubuntu_test",
            native_session_id="agy-wsl-99",
            source_timestamp="2026-11-19T13:00:00Z",
            observed_timestamp="2026-11-19T13:00:00Z",
            source_adapter_version="0.1.0",
            payload={
                "environment": {
                    "environment_id": "env_wsl_ubuntu_test",
                    "runtime_kind": "wsl",
                    "distro": "Ubuntu",
                    "hostname": "Xeres",
                    "label": "WSL Ubuntu",
                },
                "first_observed_at": "2026-11-19T13:00:00Z",
            },
        ),
    )
    append_event(
        wsl_home,
        EventEnvelope(
            event_id="evt_wsl_assoc_1",
            event_schema_version=1,
            event_type=EventType.ASSOCIATION_CREATED.value,
            provider="agy",
            environment_id="env_wsl_ubuntu_test",
            native_session_id="agy-wsl-99",
            source_timestamp="2026-11-19T13:00:01Z",
            observed_timestamp="2026-11-19T13:00:01Z",
            source_adapter_version="0.1.0",
            payload={
                "association_id": "assoc_wsl_99",
                "workflow_id": wf_id,
                "evidence_level": "confirmed",
                "association_method": "manual_link",
                "status": "active",
            },
        ),
    )

    # Windows find_sessions ingests wsl_spool automatically and finds the WSL2 session
    found = svc.find_sessions(workflow_identifier="cross")
    assert len(found["sessions"]) == 1
    assert found["sessions"][0]["session"]["environment_id"] == "env_wsl_ubuntu_test"
    assert found["sessions"][0]["session"]["native_session_id"] == "agy-wsl-99"

    # Re-syncing does not duplicate
    res2 = svc.materializer.sync_from_spools()
    assert res2.ingested_count == 0
    assert len(res2.issues) == 1
    assert "does not exist or is inaccessible" in res2.issues[0].reason

    # Diagnose explicitly flags the missing external spool root
    diag = svc.diagnose()
    assert diag["status"] == "degraded"
    assert diag["spools"]["issue_count"] == 1
