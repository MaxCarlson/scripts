"""Tests for durable event spools, idempotency, failure recovery, and SQLite rebuild."""

from __future__ import annotations

import json
from pathlib import Path

from agent_continuity.events import append_event, discover_spool_roots, read_spool_events
from agent_continuity.materializer import SQLiteMaterializer
from agent_continuity.models import EventEnvelope, EventType
from agent_continuity.service import ContinuityService


def test_durable_replay_and_rebuild_preserve_all_user_decisions(tmp_path: Path) -> None:
    home = tmp_path / "state"
    svc = ContinuityService(home_dir=home)

    wf = svc.add_workflow(
        slug="procwatch",
        title="ProcWatch Development",
        urls=["https://chatgpt.com/c/11111111-2222-3333-4444-555555555555"],
        repo_paths=[r"C:\Users\mcarls\src\scripts"],
        apply=True,
    )
    wf2 = svc.add_workflow(slug="other-wf", title="Other Workflow", apply=True)
    wf_id = wf.details["workflow_id"]

    svc.add_gui_conversation(wf_id, url="https://chatgpt.com/c/99999999-aaaa-bbbb-cccc-dddddddddddd", apply=True)
    svc.link_session(
        workflow_identifier=wf_id,
        provider="codex",
        native_session_id="codex-1",
        environment_selector="windows",
        cwd=r"C:\Users\mcarls\src\scripts",
        apply=True,
    )
    svc.link_session(
        workflow_identifier=wf_id,
        provider="agy",
        native_session_id="agy-cand",
        environment_selector="wsl:Ubuntu",
        evidence_level="candidate",
        apply=True,
    )
    svc.reject_candidate(
        workflow_identifier=wf_id,
        provider="agy",
        native_session_id="agy-cand",
        environment_selector="wsl:Ubuntu",
        note="Wrong session",
        apply=True,
    )
    svc.update_session_status(
        provider="codex",
        native_session_id="codex-1",
        lifecycle_status="completed",
        environment_selector="windows",
        apply=True,
    )
    svc.archive_workflow(wf2.details["workflow_id"], apply=True)

    before_find = svc.find_sessions(workflow_identifier="procwatch")
    before_wfs = [w.to_dict() for w in svc.list_workflows(status="all")]

    # Delete materialized SQLite index and sidecars completely
    db_path = home / "index.sqlite"
    assert db_path.exists()
    db_path.unlink()
    for suffix in ("-wal", "-shm"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)

    rebuild = svc.rebuild_index(apply=True)
    assert rebuild["rebuilt"] is True
    assert rebuild["issues"] == []

    after_find = svc.find_sessions(workflow_identifier="procwatch")
    after_wfs = [w.to_dict() for w in svc.list_workflows(status="all")]

    assert after_wfs == before_wfs
    assert after_find["workflow"] == before_find["workflow"]
    assert len(after_find["sessions"]) == 1
    assert after_find["sessions"][0]["session"]["lifecycle_status"] == "completed"
    assert after_find["sessions"][0]["association"]["evidence_level"] == "confirmed"

    # Candidate rejection must survive rebuild
    inbox = svc.list_inbox()
    assert inbox["candidate_associations"] == []


def test_event_ingestion_is_idempotent_across_replays(tmp_path: Path) -> None:
    home = tmp_path / "state"
    svc = ContinuityService(home_dir=home)
    svc.add_workflow(slug="alpha", title="Alpha", apply=True)
    svc.link_session(
        workflow_identifier="alpha",
        provider="codex",
        native_session_id="s-1",
        environment_selector="windows",
        apply=True,
    )

    mat = SQLiteMaterializer(home)
    first_sync = mat.sync_from_spools()
    second_sync = mat.sync_from_spools()
    assert first_sync.ingested_count == 0
    assert second_sync.ingested_count == 0
    assert second_sync.skipped_duplicates == first_sync.skipped_duplicates
    assert len(mat.list_workflows(status="all")) == 1
    assert len(mat.list_associations()) == 1


def test_corrupt_and_partial_spool_files_do_not_break_valid_recovery(tmp_path: Path) -> None:
    home = tmp_path / "state"
    svc = ContinuityService(home_dir=home)
    svc.add_workflow(slug="alpha", title="Alpha", apply=True)
    svc.link_session(
        workflow_identifier="alpha",
        provider="codex",
        native_session_id="s-ok",
        environment_selector="windows",
        apply=True,
    )

    # Inject corrupt, zero-byte, and schema-invalid files into the spool
    bad_dir = home / "events" / "env_broken"
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / "001_truncated.json").write_text('{"event_id": "bad"', encoding="utf-8")
    (bad_dir / "002_empty.json").write_text("", encoding="utf-8")
    (bad_dir / "003_missing_fields.json").write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    # Also a temp file that must be ignored cleanly
    (bad_dir / ".tmp.1234.abcd.json").write_text("partial", encoding="utf-8")

    scan = read_spool_events(discover_spool_roots(home))
    assert len(scan.issues) == 3

    rebuild = svc.rebuild_index(apply=True)
    assert len(rebuild["issues"]) == 3
    found = svc.find_sessions(workflow_identifier="alpha")
    assert len(found["sessions"]) == 1
    assert found["sessions"][0]["session"]["native_session_id"] == "s-ok"

    diag = svc.diagnose()
    assert diag["status"] == "degraded"
    assert diag["spools"]["issue_count"] == 3


def test_observed_session_event_does_not_fabricate_native_created_at(tmp_path: Path) -> None:
    home = tmp_path / "state"
    mat = SQLiteMaterializer(home)
    ev = EventEnvelope(
        event_id="evt_obs_1",
        event_schema_version=1,
        event_type=EventType.SESSION_OBSERVED.value,
        provider="agy",
        environment_id="env_wsl_ubuntu",
        native_session_id="agy-99",
        source_timestamp="2026-11-19T10:00:00Z",
        observed_timestamp="2026-11-19T10:00:01Z",
        source_adapter_version="0.1.0",
        payload={
            "first_observed_at": "2026-11-19T10:00:01Z",
            "last_seen_at": "2026-11-19T10:00:01Z",
            "metadata_source": "hook",
        },
    )
    append_event(home, ev)
    mat.sync_from_spools()
    sess = mat.get_session("agy", "env_wsl_ubuntu", "agy-99")
    assert sess is not None
    assert sess.created_at is None
    assert sess.first_observed_at == "2026-11-19T10:00:01Z"
