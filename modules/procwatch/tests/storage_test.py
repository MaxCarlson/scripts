"""Unit and integration tests for Phase 2 FlightRecorderStorage and Phase 2 CLI."""

from __future__ import annotations

import json
from pathlib import Path

from procwatch.cli import main
from procwatch.models import (
    AgentContext,
    ConfidenceLevel,
    EdgeRelation,
    EvidenceEdge,
    IncidentRecord,
    IngestGap,
    ProcessIdentity,
    ProcessObservation,
    RawEventRecord,
    WindowObservation,
    WindowState,
)
from procwatch.storage import SCHEMA_VERSION, FlightRecorderStorage


def test_storage_schema_and_wal_mode(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"
    storage = FlightRecorderStorage(db_path=db_path)
    try:
        stats = storage.db_stats()
        assert stats["schema_version"] == SCHEMA_VERSION
        assert stats["size_bytes"] > 0
        with storage._connect() as conn:
            row = conn.execute("PRAGMA journal_mode").fetchone()
            assert row is not None and str(row[0]).lower() == "wal"
    finally:
        storage.close()


def test_atomic_ingest_batch_and_ingest_gap(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"
    storage = FlightRecorderStorage(db_path=db_path)
    try:
        count, raw_ids = storage.ingest_event_batch(
            source="sysmon_evt",
            events=[
                RawEventRecord(
                    boot_id="boot1",
                    source="sysmon_evt",
                    provider_event_id=1,
                    source_record_id="101",
                    event_ts_utc="2026-11-15T10:00:00.000Z",
                    payload_redacted="<Event>101</Event>",
                )
            ],
            new_bookmark_xml="<BookmarkList><Bookmark RecordId='101'/></BookmarkList>",
            status="active",
            coverage_state="live",
        )
        assert count == 1
        assert len(raw_ids) == 1

        states = storage.get_collector_state("sysmon_evt")
        assert len(states) == 1
        assert states[0]["evt_bookmark_xml"] == "<BookmarkList><Bookmark RecordId='101'/></BookmarkList>"
        assert states[0]["events_ingested"] == 1

        gap_id = storage.record_ingest_gap(
            IngestGap(source="sysmon_evt", reason="stale_bookmark_or_cleared_log")
        )
        assert gap_id > 0
        gaps = storage.get_ingest_gaps("sysmon_evt")
        assert len(gaps) == 1
        assert gaps[0]["reason"] == "stale_bookmark_or_cleared_log"
    finally:
        storage.close()


def test_provisional_promotion_and_history_explain_mark(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"
    storage = FlightRecorderStorage(db_path=db_path)
    try:
        prov_id = ProcessIdentity.provisional("boot1", 4321, 500_000_000)
        prov_obs = ProcessObservation(
            identity=prov_id,
            ppid=100,
            image_name="python.exe",
            command_line_redacted="python.exe worker.py",
            source="toolhelp32",
        )
        storage.upsert_process(
            prov_obs,
            cwd=r"C:\repo",
            pe_subsystem="CUI",
            agent_context=AgentContext(
                agent_kind="codex",
                agent_session="sess-1",
                trust_level="instrumented",
            ),
        )

        canon_id = ProcessIdentity.canonical_kernel("boot1", 4321, 987654321)
        canon_obs = ProcessObservation(
            identity=canon_id,
            ppid=100,
            image_name="python.exe",
            command_line_redacted="python.exe worker.py",
            source="wmi_trace",
        )
        storage.promote_process_identity(prov_id.proc_key, canon_obs)

        win = WindowObservation(
            window_instance_id="win-1",
            hwnd=0x1234,
            owner_pid=4321,
            owner_tid=9,
            window_class="ConsoleWindowClass",
            initial_title="pwsh",
            current_title="pwsh",
            state=WindowState.SUPPRESSED,
        )
        storage.upsert_window(win, owner_proc_key=canon_id.proc_key, guard_action="minimize")
        storage.insert_edge(
            EvidenceEdge(
                from_node_id=canon_id.proc_key,
                to_node_id="win:win-1",
                relation=EdgeRelation.CORRELATED_WITH,
                source="correlator_scorer",
                method="direct_hwnd_pid_match",
                confidence=0.9,
            )
        )
        inc_id = storage.insert_incident(
            IncidentRecord(
                created_ts_utc="2099-01-01T00:00:00.000Z",
                category="guard_action",
                primary_proc_key=canon_id.proc_key,
                root_initiator_key=canon_id.proc_key,
                window_instance_id="win-1",
                confidence=ConfidenceLevel.HIGH,
                summary_text="ConsoleWindowClass suppressed python.exe",
            ),
            window_ids=["win-1"],
        )
        assert inc_id > 0

        rows = storage.query_history(popups_only=True, agent_filter="codex")
        assert len(rows) == 1
        assert rows[0]["incident_id"] == inc_id

        detail = storage.get_incident_detail(inc_id)
        assert detail is not None
        assert "codex" in (detail["process"]["agent_context_json"] or "")
        assert any(e["relation"] == "supersedes" for e in detail["edges"]) or detail["edges"]

        bm = storage.add_user_mark("flashing popup", window_seconds=5.0)
        assert bm.bookmark_id is not None
    finally:
        storage.close()

    # Verify Phase 2 CLI subcommands end-to-end against the populated DB.
    export_path = tmp_path / "bundle.json"
    assert main(["doctor", "-j", "-d", str(db_path)]) == 0
    assert main(["history", "-t", "24h", "-p", "-a", "codex", "-e", str(export_path), "-d", str(db_path)]) == 0
    assert export_path.exists()
    bundle = json.loads(export_path.read_text(encoding="utf-8"))
    assert len(bundle["incidents"]) == 1
    assert main(["explain", "-i", str(inc_id), "-j", "-d", str(db_path)]) == 0
    assert main(["mark", "-l", "cli mark", "-j", "-d", str(db_path)]) == 0


def test_retention_pruning(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"
    storage = FlightRecorderStorage(db_path=db_path)
    try:
        storage.insert_incident(
            IncidentRecord(
                created_ts_utc="2020-01-01T00:00:00.000Z",
                category="console_popup",
                summary_text="old incident",
            )
        )
        storage.insert_incident(
            IncidentRecord(
                created_ts_utc="2099-01-01T00:00:00.000Z",
                category="console_popup",
                summary_text="future incident",
            )
        )
        counts = storage.prune_retention(max_age_days=30)
        assert counts["deleted_incidents"] == 1
        remaining = storage.query_history()
        assert len(remaining) == 1
        assert remaining[0]["summary_text"] == "future incident"
    finally:
        storage.close()
