from pathlib import Path
import pytest

from script_logging.invocation_store import InvocationStore
from script_logging.reconciliation import reconcile_invocation_summaries


def test_reconciliation_detects_and_fixes_drift(tmp_path: Path):
    db_path = tmp_path / "invocations.sqlite3"
    store = InvocationStore(db_path)
    inv_id = store.start_invocation(
        program_id="module:mangadl",
        invoked_name="mangadl",
        argv=("mangadl", "run"),
        cwd=Path("/tmp"),
        origin="launcher",
    )
    store.finish_invocation(inv_id, exit_code=0, status="exited")

    # Artificially tamper with program_usage counter
    with store._connect() as conn:
        conn.execute("UPDATE program_usage SET success_count = 999 WHERE program_id = 'module:mangadl'")

    # Dry-run detects mismatch without changing
    report_dry = reconcile_invocation_summaries(db_path, dry_run=True)
    assert report_dry.mismatches_found > 0
    assert report_dry.corrections_applied == 0
    assert any("program_usage" in d and "999" in d for d in report_dry.details)

    # Counter should still be tampered
    with store._connect() as conn:
        tampered = conn.execute("SELECT success_count FROM program_usage WHERE program_id = 'module:mangadl'").fetchone()[0]
        assert tampered == 999

    # Apply fixes
    report_apply = reconcile_invocation_summaries(db_path, dry_run=False)
    assert report_apply.corrections_applied > 0

    # Verify counter is restored to actual truth (1)
    with store._connect() as conn:
        count = conn.execute("SELECT success_count FROM program_usage WHERE program_id = 'module:mangadl'").fetchone()[0]
        assert count == 1

    # Verify subsequent reconciliation finds 0 mismatches
    report_clean = reconcile_invocation_summaries(db_path, dry_run=True)
    assert report_clean.mismatches_found == 0
    assert report_clean.corrections_applied == 0


def test_reconciliation_missing_db(tmp_path: Path):
    missing_path = tmp_path / "missing.sqlite3"
    with pytest.raises(FileNotFoundError):
        reconcile_invocation_summaries(missing_path)


def test_reconciliation_repairs_missing_pattern_and_orphan_alias(tmp_path: Path):
    db_path = tmp_path / "invocations.sqlite3"
    store = InvocationStore(db_path)
    inv_id = store.start_invocation(
        program_id="module:mangadl",
        invoked_name="mangadl",
        argv=("mangadl", "run"),
        cwd=Path("/tmp"),
        origin="launcher",
    )
    store.finish_invocation(inv_id, exit_code=0, status="exited")

    # Delete pattern row and insert phantom alias row
    with store._connect() as conn:
        conn.execute("DELETE FROM command_patterns")
        conn.execute(
            """
            INSERT INTO alias_usage (
                invoked_name, program_id, total_starts, success_count, failure_count, unknown_count,
                first_seen_utc, last_seen_utc
            ) VALUES ('phantom', 'module:phantom', 42, 0, 42, 0, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
            """
        )

    # Dry-run
    report_dry = reconcile_invocation_summaries(db_path, dry_run=True)
    assert report_dry.mismatches_found >= 2

    # Apply
    report_apply = reconcile_invocation_summaries(db_path, dry_run=False)
    assert report_apply.corrections_applied >= 2

    # Check that pattern was recreated and phantom alias deleted
    with store._connect() as conn:
        pattern_row = conn.execute("SELECT * FROM command_patterns").fetchone()
        assert pattern_row is not None
        assert pattern_row["invocation_count"] == 1
        assert pattern_row["success_count"] == 1

        phantom = conn.execute("SELECT * FROM alias_usage WHERE invoked_name = 'phantom'").fetchone()
        assert phantom is None
