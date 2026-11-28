"""Tests for durable event spools, idempotency, failure recovery, and SQLite rebuild."""

from __future__ import annotations

import json
import os
import threading
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_continuity.errors import ContinuityError, ErrorCode
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

    def _counting_read(path: Path, *, max_event_bytes: int):
        nonlocal parse_calls
        parse_calls += 1
        return orig_read(path, max_event_bytes=max_event_bytes)

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


def test_incremental_sync_same_size_preserved_mtime_concurrent_writers_and_repair(tmp_path: Path) -> None:
    """Qualify same-size+preserved-mtime replacement, concurrent writers/syncs, tx rollback, and malformed repair."""
    import json
    import os
    from concurrent.futures import ThreadPoolExecutor

    import pytest

    from agent_continuity.errors import ContinuityError

    home = tmp_path / "state_conc"
    mat = SQLiteMaterializer(home)

    # 1. Same-size replacement with preserved mtime_ns is detected via st_ino / st_ctime_ns
    ev_a = EventEnvelope(
        event_id="evt_same_001",
        event_schema_version=1,
        event_type=EventType.SESSION_OBSERVED.value,
        provider="codex",
        environment_id="env_win_1",
        native_session_id="sid_aaa",
        source_timestamp="2026-11-27T11:00:00Z",
        observed_timestamp="2026-11-27T11:00:01Z",
        source_adapter_version="2.3.0",
        payload={"first_observed_at": "2026-11-27T11:00:01Z", "last_seen_at": "2026-11-27T11:00:01Z"},
    )
    p_a = append_event(home, ev_a)
    assert mat.sync_from_spools().ingested_count == 1
    orig_st = p_a.stat()
    tmp_rep = p_a.with_name(".tmp.replace.json")
    tmp_rep.write_text(
        p_a.read_text(encoding="utf-8").replace("evt_same_001", "evt_same_002").replace("sid_aaa", "sid_bbb"),
        encoding="utf-8",
        newline="\n",
    )
    assert tmp_rep.stat().st_size == orig_st.st_size
    os.utime(tmp_rep, ns=(orig_st.st_atime_ns, orig_st.st_mtime_ns))
    os.replace(tmp_rep, p_a)

    rep_sync = mat.sync_from_spools()
    assert rep_sync.ingested_count == 1
    assert mat.get_session("codex", "env_win_1", "sid_bbb") is not None

    # 2. Explicit full verification path detects even in-place identical-stat tampering if forced
    ver_sync = mat.sync_from_spools(verify_checksums=True)
    assert ver_sync.ingested_count == 0
    assert ver_sync.skipped_duplicates == 1

    # 3. Malformed file -> SpoolIssue -> repaired -> ingested cleanly
    bad_path = home / "events" / "env_win_1" / "20261127T110002Z_evt_bad_1.json"
    bad_path.write_text("{corrupt", encoding="utf-8")
    bad_res = mat.sync_from_spools()
    assert len(bad_res.issues) == 1
    ev_repaired = EventEnvelope(
        event_id="evt_bad_1",
        event_schema_version=1,
        event_type=EventType.SESSION_OBSERVED.value,
        provider="codex",
        environment_id="env_win_1",
        native_session_id="sid_repaired",
        source_timestamp="2026-11-27T11:00:02Z",
        observed_timestamp="2026-11-27T11:00:03Z",
        source_adapter_version="2.3.0",
        payload={"first_observed_at": "2026-11-27T11:00:03Z", "last_seen_at": "2026-11-27T11:00:03Z"},
    )
    bad_path.write_text(json.dumps(ev_repaired.to_dict()), encoding="utf-8")
    rep_ok = mat.sync_from_spools()
    assert rep_ok.issues == []
    assert rep_ok.ingested_count == 1
    assert mat.get_session("codex", "env_win_1", "sid_repaired") is not None

    # 4. Transaction interruption does not leave partial fingerprint/event state
    ev_tx = EventEnvelope(
        event_id="evt_tx_fail",
        event_schema_version=1,
        event_type=EventType.SESSION_OBSERVED.value,
        provider="codex",
        environment_id="env_win_1",
        native_session_id="sid_tx_fail",
        source_timestamp="2026-11-27T11:00:04Z",
        observed_timestamp="2026-11-27T11:00:05Z",
        source_adapter_version="2.3.0",
        payload={"first_observed_at": "2026-11-27T11:00:05Z", "last_seen_at": "2026-11-27T11:00:05Z"},
    )
    p_tx = append_event(home, ev_tx)
    orig_apply = mat._apply_event_in_tx

    def _boom_apply(conn, event, *, spool_file=None, checksum="", **kwargs):
        if event.event_id == "evt_tx_fail":
            raise RuntimeError("simulated_tx_interruption")
        return orig_apply(conn, event, spool_file=spool_file, checksum=checksum, **kwargs)

    mat._apply_event_in_tx = _boom_apply  # type: ignore[method-assign]
    with pytest.raises(ContinuityError, match="simulated_tx_interruption"):
        mat.sync_from_spools()
    mat._apply_event_in_tx = orig_apply  # type: ignore[method-assign]
    assert mat.get_session("codex", "env_win_1", "sid_tx_fail") is None
    # Next sync recovers cleanly because fingerprint was rolled back with the transaction
    recovered = mat.sync_from_spools()
    assert recovered.ingested_count == 1
    assert mat.get_session("codex", "env_win_1", "sid_tx_fail") is not None
    assert p_tx.exists()

    # 5. Concurrent writers and overlapping syncs preserve all events without corruption
    def _writer(idx: int) -> str:
        ev = EventEnvelope(
            event_id=f"evt_conc_{idx:03d}",
            event_schema_version=1,
            event_type=EventType.SESSION_OBSERVED.value,
            provider="codex",
            environment_id="env_win_1",
            native_session_id=f"sid_conc_{idx:03d}",
            source_timestamp="2026-11-27T11:01:00Z",
            observed_timestamp=f"2026-11-27T11:01:{idx:02d}Z",
            source_adapter_version="2.3.0",
            payload={"first_observed_at": "2026-11-27T11:01:00Z", "last_seen_at": "2026-11-27T11:01:00Z"},
        )
        append_event(home, ev)
        if idx % 3 == 0:
            mat.sync_from_spools()
        return ev.event_id

    with ThreadPoolExecutor(max_workers=6) as pool:
        ids = list(pool.map(_writer, range(18)))

    final = mat.sync_from_spools()
    assert final.issues == []
    for i in range(18):
        assert mat.get_session("codex", "env_win_1", f"sid_conc_{i:03d}") is not None
    assert len(ids) == 18
    rebuilt = mat.rebuild_from_spools()
    assert rebuilt.rebuilt is True
    assert rebuilt.ingested_count == 21


def test_checksum_conflict_legacy_empty_handle_race_and_rebuild_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    mat = SQLiteMaterializer(home)

    ev1 = EventEnvelope(
        event_id="evt_conflict_001",
        event_schema_version=1,
        event_type=EventType.SESSION_OBSERVED.value,
        provider="codex",
        environment_id="env_win_1",
        native_session_id="sid_conflict_001",
        source_timestamp="2026-11-27T01:00:00Z",
        observed_timestamp="2026-11-27T01:00:00Z",
        source_adapter_version="2.3.0",
        payload={
            "first_observed_at": "2026-11-27T01:00:00Z",
            "last_seen_at": "2026-11-27T01:00:00Z",
            "title": "Original Title",
            "cwd": str(tmp_path),
        },
    )
    p1 = append_event(home, ev1)
    first_sync = mat.sync_from_spools()
    assert first_sync.issues == []
    assert first_sync.ingested_count == 1

    # 1. Same event_id with modified content in a second spool file -> checksum conflict
    ev_modified = EventEnvelope(
        event_id="evt_conflict_001",
        event_schema_version=1,
        event_type=EventType.SESSION_OBSERVED.value,
        provider="codex",
        environment_id="env_win_1",
        native_session_id="sid_conflict_001",
        source_timestamp="2026-11-27T01:00:00Z",
        observed_timestamp="2026-11-27T01:00:00Z",
        source_adapter_version="2.3.0",
        payload={
            "first_observed_at": "2026-11-27T01:00:00Z",
            "last_seen_at": "2026-11-27T01:00:00Z",
            "title": "Tampered Title",
            "cwd": str(tmp_path),
        },
    )
    env_dir = p1.parent
    conflict_file = env_dir / "9999-conflict.json"
    conflict_file.write_text(json.dumps(ev_modified.to_dict()), encoding="utf-8")

    conflict_sync = mat.sync_from_spools()
    assert any(
        issue.file_path == str(conflict_file) and "conflicting checksum" in issue.reason.lower()
        for issue in conflict_sync.issues
    )
    with closing(mat._connect_rw()) as conn:  # noqa: SLF001
        cached = conn.execute(
            "SELECT 1 FROM spool_file_fingerprints WHERE spool_file = ?",
            (str(conflict_file),),
        ).fetchone()
    assert cached is None

    with pytest.raises(ContinuityError) as exc_info:
        mat.ingest_events([(ev_modified, None, "")])
    assert exc_info.value.code == ErrorCode.ASSOCIATION_CONFLICT
    conflict_file.unlink()

    # 2. Legacy ingested_events row with empty checksum ("")
    with closing(mat._connect_rw()) as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE ingested_events SET checksum = '' WHERE event_id = ?",
            ("evt_conflict_001",),
        )
        conn.execute("DELETE FROM spool_file_fingerprints")
        conn.commit()

    legacy_sync = mat.sync_from_spools()
    assert legacy_sync.issues == []
    assert legacy_sync.skipped_duplicates >= 1
    with closing(mat._connect_rw()) as conn:  # noqa: SLF001
        row = conn.execute(
            "SELECT checksum FROM ingested_events WHERE event_id = ?",
            ("evt_conflict_001",),
        ).fetchone()
        assert row is not None and row[0] == ""
        conn.execute("DELETE FROM spool_file_fingerprints")
        conn.commit()

    verified_sync = mat.sync_from_spools(verify_checksums=True)
    assert any(
        "empty checksum" in issue.reason.lower()
        for issue in verified_sync.issues
    )
    with closing(mat._connect_rw()) as conn:  # noqa: SLF001
        cached_legacy = conn.execute(
            "SELECT 1 FROM spool_file_fingerprints WHERE spool_file = ?",
            (str(p1),),
        ).fetchone()
    assert cached_legacy is None

    # Restore valid checksum before testing handle/path stat mismatch & st_ino==0
    mat.rebuild_from_spools()

    # 3a. Identical-stat replacement during read/stat boundary (different st_ino on path stat)
    ev_race = EventEnvelope(
        event_id="evt_race_001",
        event_schema_version=1,
        event_type=EventType.SESSION_OBSERVED.value,
        provider="codex",
        environment_id="env_win_1",
        native_session_id="sid_race_001",
        source_timestamp="2026-11-27T01:05:00Z",
        observed_timestamp="2026-11-27T01:05:00Z",
        source_adapter_version="2.3.0",
        payload={
            "first_observed_at": "2026-11-27T01:05:00Z",
            "last_seen_at": "2026-11-27T01:05:00Z",
            "cwd": str(tmp_path),
        },
    )
    p_race = append_event(home, ev_race)
    real_os_stat = os.stat

    def _clone_stat(st: Any, *, st_ino: int) -> SimpleNamespace:
        return SimpleNamespace(
            st_size=st.st_size,
            st_mtime_ns=st.st_mtime_ns,
            st_ctime_ns=st.st_ctime_ns,
            st_birthtime_ns=getattr(st, "st_birthtime_ns", st.st_ctime_ns),
            st_ino=st_ino,
            st_dev=st.st_dev,
        )

    def _spoof_ino_stat(path: Any, *args: Any, **kwargs: Any) -> Any:
        st = real_os_stat(path, *args, **kwargs)
        if Path(path) == p_race:
            return _clone_stat(st, st_ino=(st.st_ino or 1) + 999999)
        return st

    monkeypatch.setattr("agent_continuity.events.os.stat", _spoof_ino_stat)
    race_sync = mat.sync_from_spools()
    monkeypatch.undo()
    assert any(
        issue.file_path == str(p_race) and "concurrent modification" in issue.reason.lower()
        for issue in race_sync.issues
    )
    with closing(mat._connect_rw()) as conn:  # noqa: SLF001
        cached_race = conn.execute(
            "SELECT 1 FROM spool_file_fingerprints WHERE spool_file = ?",
            (str(p_race),),
        ).fetchone()
    assert cached_race is None

    # 3b. st_ino == 0 on both fstat and os.stat -> ingests cleanly but declines caching
    real_os_fstat = os.fstat

    def _zero_ino_stat(path: Any, *args: Any, **kwargs: Any) -> Any:
        st = real_os_stat(path, *args, **kwargs)
        if Path(path) == p_race:
            return _clone_stat(st, st_ino=0)
        return st

    def _zero_ino_fstat(fd: int) -> Any:
        st = real_os_fstat(fd)
        return _clone_stat(st, st_ino=0)

    monkeypatch.setattr("agent_continuity.events.os.stat", _zero_ino_stat)
    monkeypatch.setattr("agent_continuity.events.os.fstat", _zero_ino_fstat)
    zero_sync = mat.sync_from_spools()
    monkeypatch.undo()
    assert zero_sync.issues == []
    assert zero_sync.ingested_count == 1
    with closing(mat._connect_rw()) as conn:  # noqa: SLF001
        cached_zero = conn.execute(
            "SELECT 1 FROM spool_file_fingerprints WHERE spool_file = ?",
            (str(p_race),),
        ).fetchone()
    assert cached_zero is None

    # 4. rebuild_from_spools holds _writer_lock on .index.sqlite.lock
    lock_entered = threading.Event()
    release_lock = threading.Event()
    rebuild_done = threading.Event()

    def _hold_writer_lock() -> None:
        with mat._writer_lock():  # noqa: SLF001
            lock_entered.set()
            release_lock.wait(timeout=5.0)

    holder = threading.Thread(target=_hold_writer_lock)
    holder.start()
    assert lock_entered.wait(timeout=2.0)

    rebuild_result: list[Any] = []

    def _run_rebuild() -> None:
        rebuild_result.append(mat.rebuild_from_spools())
        rebuild_done.set()

    rebuilder = threading.Thread(target=_run_rebuild)
    rebuilder.start()
    assert not rebuild_done.wait(timeout=0.15)
    release_lock.set()
    holder.join(timeout=5.0)
    rebuilder.join(timeout=5.0)
    assert rebuild_done.is_set()
    assert rebuild_result[0].rebuilt is True
    assert rebuild_result[0].ingested_count == 2
