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


def test_sync_with_only_projected_events_does_not_open_a_writer(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "state"
    svc = ContinuityService(home_dir=home)
    svc.add_workflow(slug="alpha", title="Alpha", apply=True)
    mat = SQLiteMaterializer(home)

    first = mat.sync_from_spools()
    assert first.ingested_count == 0
    assert first.skipped_duplicates > 0

    def unexpected_writer(*args, **kwargs):
        raise AssertionError("No-op spool synchronization must not open a write transaction.")

    monkeypatch.setattr(mat, "_connect_rw", unexpected_writer)
    second = mat.sync_from_spools()
    assert second.ingested_count == 0
    assert second.skipped_duplicates == first.skipped_duplicates


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


def test_incremental_spool_sync_preserves_authority_and_handles_changes(tmp_path: Path, monkeypatch) -> None:
    """Verify incremental sync skips unchanged files while detecting appends, duplicates, truncations, and replacements."""
    import json

    from agent_continuity import events as events_mod

    home = tmp_path / "state_inc"
    mat = SQLiteMaterializer(home)

    ev1 = EventEnvelope(
        event_id="evt_inc_1",
        event_schema_version=1,
        event_type=EventType.SESSION_OBSERVED.value,
        provider="codex",
        environment_id="env_win_1",
        native_session_id="sid_inc_1",
        source_timestamp="2026-11-27T10:00:00Z",
        observed_timestamp="2026-11-27T10:00:01Z",
        source_adapter_version="2.3.0",
        payload={"first_observed_at": "2026-11-27T10:00:01Z", "last_seen_at": "2026-11-27T10:00:01Z"},
    )
    p1 = append_event(home, ev1)
    first = mat.sync_from_spools()
    assert first.ingested_count == 1
    assert first.total_spool_events == 1

    # Unchanged warm sync must NOT re-read/re-parse ev1's JSON file
    parse_calls = 0
    orig_read = events_mod._read_and_validate_spool_file

    def _counting_read(path: Path, *, size: int, max_event_bytes: int):
        nonlocal parse_calls
        parse_calls += 1
        return orig_read(path, size=size, max_event_bytes=max_event_bytes)

    monkeypatch.setattr(events_mod, "_read_and_validate_spool_file", _counting_read)

    warm = mat.sync_from_spools()
    assert warm.ingested_count == 0
    assert warm.skipped_duplicates == 1
    assert warm.total_spool_events == 1
    assert parse_calls == 0

    # Concurrent append: only the newly appended file is parsed
    ev2 = EventEnvelope(
        event_id="evt_inc_2",
        event_schema_version=1,
        event_type=EventType.SESSION_OBSERVED.value,
        provider="codex",
        environment_id="env_win_1",
        native_session_id="sid_inc_2",
        source_timestamp="2026-11-27T10:00:02Z",
        observed_timestamp="2026-11-27T10:00:03Z",
        source_adapter_version="2.3.0",
        payload={"first_observed_at": "2026-11-27T10:00:03Z", "last_seen_at": "2026-11-27T10:00:03Z"},
    )
    p2 = append_event(home, ev2)
    inc = mat.sync_from_spools()
    assert inc.ingested_count == 1
    assert inc.skipped_duplicates == 1
    assert inc.total_spool_events == 2
    assert parse_calls == 1

    # Rotated/copied duplicate file with same event_id is parsed and deduplicated cleanly
    rotated = p2.with_name("rotated_copy_evt_inc_2.json")
    rotated.write_text(p2.read_text(encoding="utf-8"), encoding="utf-8")
    dup_res = mat.sync_from_spools()
    assert dup_res.ingested_count == 0
    assert dup_res.skipped_duplicates == 3
    assert parse_calls == 2

    # Truncated existing file (size=0) is NOT silently skipped; produces SpoolIssue
    p1.write_text("", encoding="utf-8")
    trunc_res = mat.sync_from_spools()
    assert len(trunc_res.issues) == 1
    assert "Zero-byte" in trunc_res.issues[0].reason
    assert parse_calls == 3

    # Replaced existing file with a new event_id is detected and ingested
    ev3 = EventEnvelope(
        event_id="evt_inc_3",
        event_schema_version=1,
        event_type=EventType.SESSION_OBSERVED.value,
        provider="codex",
        environment_id="env_win_1",
        native_session_id="sid_inc_3",
        source_timestamp="2026-11-27T10:00:04Z",
        observed_timestamp="2026-11-27T10:00:05Z",
        source_adapter_version="2.3.0",
        payload={"first_observed_at": "2026-11-27T10:00:05Z", "last_seen_at": "2026-11-27T10:00:05Z"},
    )
    p1.write_text(json.dumps(ev3.to_dict()), encoding="utf-8")
    rep_res = mat.sync_from_spools()
    assert rep_res.ingested_count == 1
    assert mat.get_session("codex", "env_win_1", "sid_inc_3") is not None

    # Full rebuild recovers cleanly and repopulates fingerprints
    rebuilt = mat.rebuild_from_spools()
    assert rebuilt.rebuilt is True
    assert rebuilt.ingested_count == 2
    parse_calls_before_warm = parse_calls
    post_rebuild_warm = mat.sync_from_spools()
    assert post_rebuild_warm.ingested_count == 0
    assert parse_calls == parse_calls_before_warm
