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
