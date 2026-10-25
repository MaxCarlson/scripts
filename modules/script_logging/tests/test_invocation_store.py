from __future__ import annotations

import pytest
from script_logging.invocation_store import InvocationStore, resolve_invocation_db_path
from script_logging.models import (
    AliasStatistics,
    CommandPattern,
    CommandStatistics,
    InvocationRecord,
    Page,
    ProgramStatistics,
    ReconciliationReport,
)


def test_resolve_invocation_db_path_env_override(monkeypatch, tmp_path):
    override = tmp_path / "custom" / "invocations.sqlite3"
    monkeypatch.setenv("SCRIPT_LOGGING_INVOCATION_DB", str(override))
    resolved = resolve_invocation_db_path(create=False)
    assert resolved == override
    assert not resolved.parent.exists()

    resolved_created = resolve_invocation_db_path(create=True)
    assert resolved_created == override
    assert resolved_created.parent.is_dir()


def test_resolve_invocation_db_path_platform_default(monkeypatch, tmp_path):
    monkeypatch.delenv("SCRIPT_LOGGING_INVOCATION_DB", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    path = resolve_invocation_db_path(create=True)
    assert "ScriptsToolkit" in str(path) or "scripts-toolkit" in str(path)
    assert path.name == "invocations.sqlite3"


def test_invocation_store_initializes_schema(tmp_path):
    db_path = tmp_path / "invocations.sqlite3"
    store = InvocationStore(db_path)
    with store._connect() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"schema_meta", "invocations", "command_patterns", "program_usage", "alias_usage"}.issubset(tables)
        version = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]
        assert version == "1"


def test_models_dataclasses():
    # Verify model instantiations and immutability (frozen)
    record = InvocationRecord(
        invocation_id="test-123",
        program_id="module:mangadl",
        invoked_name="mangadl",
        origin="launcher",
        pattern_id="pat-456",
        raw_argv=("mangadl", "run"),
        redacted_argv=("mangadl", "run"),
        is_redacted=False,
        cwd="/work",
        started_at_utc="2026-10-24T12:00:00Z",
        started_epoch_ms=1792843200000,
        status="started",
    )
    assert record.invocation_id == "test-123"
    with pytest.raises(Exception):
        record.status = "exited"  # Immutable

    stats = ProgramStatistics(
        program_id="module:mangadl",
        total_starts=10,
        success_count=8,
        failure_count=2,
    )
    assert stats.total_starts == 10

    alias_stats = AliasStatistics(
        invoked_name="mangadl",
        program_id="module:mangadl",
        total_starts=5,
        success_count=4,
        failure_count=1,
    )
    assert alias_stats.invoked_name == "mangadl"

    pattern = CommandPattern(
        pattern_id="pat-1",
        program_id="module:mangadl",
        pattern_argv=("mangadl", "dl"),
        pattern_argv_json='["mangadl", "dl"]',
        invocation_count=5,
        success_count=5,
        failure_count=0,
        first_seen_utc="2026-10-24T12:00:00Z",
        last_seen_utc="2026-10-24T12:05:00Z",
    )
    assert pattern.invocation_count == 5

    cmd_stats = CommandStatistics(
        pattern_id="pat-1",
        program_id="module:mangadl",
        pattern_argv=("mangadl", "dl"),
        invocation_count=5,
        success_count=5,
        failure_count=0,
    )
    assert cmd_stats.invocation_count == 5

    page = Page(items=[record], next_cursor="next", has_more=True)
    assert len(page.items) == 1
    assert page.next_cursor == "next"

    recon = ReconciliationReport(mismatches_found=1, corrections_applied=1)
    assert recon.mismatches_found == 1


def test_start_and_finish_invocation_lifecycle(tmp_path):
    store = InvocationStore(tmp_path / "invocations.sqlite3")
    inv_id = store.start_invocation(
        program_id="module:mangadl",
        invoked_name="mangadl",
        argv=("mangadl", "chapter", "1"),
        cwd=tmp_path / "work",
        origin="launcher",
    )
    assert inv_id is not None

    record = store.get_invocation(inv_id)
    assert record is not None
    assert record.status == "started"
    assert record.exit_code is None
    assert record.program_id == "module:mangadl"
    assert record.invoked_name == "mangadl"
    assert record.raw_argv == ("mangadl", "chapter", "1")
    assert record.redacted_argv == ("mangadl", "chapter", "1")
    assert record.is_redacted is False

    # Check pattern and usage counters incremented on start
    with store._connect() as conn:
        usage = conn.execute(
            "SELECT total_starts, success_count FROM program_usage WHERE program_id='module:mangadl'"
        ).fetchone()
        assert usage["total_starts"] == 1
        assert usage["success_count"] == 0

        alias = conn.execute(
            "SELECT total_starts, success_count FROM alias_usage WHERE invoked_name='mangadl' AND program_id='module:mangadl'"
        ).fetchone()
        assert alias["total_starts"] == 1
        assert alias["success_count"] == 0

        pat = conn.execute(
            "SELECT invocation_count, success_count FROM command_patterns WHERE pattern_id=?",
            (record.pattern_id,),
        ).fetchone()
        assert pat["invocation_count"] == 1
        assert pat["success_count"] == 0

    # Finish invocation successfully
    store.finish_invocation(inv_id, exit_code=0, status="exited")
    record_finished = store.get_invocation(inv_id)
    assert record_finished is not None
    assert record_finished.status == "exited"
    assert record_finished.exit_code == 0
    assert record_finished.duration_ms is not None

    # Check counter incremented exactly once
    with store._connect() as conn:
        usage = conn.execute(
            "SELECT total_starts, success_count, failure_count FROM program_usage WHERE program_id='module:mangadl'"
        ).fetchone()
        assert usage["total_starts"] == 1
        assert usage["success_count"] == 1
        assert usage["failure_count"] == 0

    # Duplicate finish must be idempotent
    store.finish_invocation(inv_id, exit_code=0, status="exited")
    with store._connect() as conn:
        usage = conn.execute(
            "SELECT total_starts, success_count FROM program_usage WHERE program_id='module:mangadl'"
        ).fetchone()
        assert usage["success_count"] == 1


def test_finish_invocation_failure(tmp_path):
    store = InvocationStore(tmp_path / "invocations.sqlite3")
    inv_id = store.start_invocation(
        program_id="module:mangadl",
        invoked_name="mangadl",
        argv=("mangadl", "fail"),
        cwd=tmp_path,
        origin="launcher",
    )
    store.finish_invocation(inv_id, exit_code=1, status="exited")
    record = store.get_invocation(inv_id)
    assert record is not None
    assert record.exit_code == 1
    assert record.status == "exited"

    with store._connect() as conn:
        usage = conn.execute(
            "SELECT total_starts, success_count, failure_count FROM program_usage WHERE program_id='module:mangadl'"
        ).fetchone()
        assert usage["total_starts"] == 1
        assert usage["success_count"] == 0
        assert usage["failure_count"] == 1


def test_get_nonexistent_invocation(tmp_path):
    store = InvocationStore(tmp_path / "invocations.sqlite3")
    assert store.get_invocation("nonexistent-id") is None
