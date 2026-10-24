"""Reconciliation tooling for restoring summary counter invariants against invocation truth."""
from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from .invocation_store import resolve_invocation_db_path
from .models import ReconciliationReport


def reconcile_invocation_summaries(
    path: Optional[Path | str] = None,
    *,
    dry_run: bool = True,
) -> ReconciliationReport:
    """Audit and reconcile summary counter tables against immutable invocations rows.

    Recomputes expected aggregates for command_patterns, program_usage, and alias_usage
    from the raw invocations log. Detects drift, missing summary records, and orphan records.
    When dry_run=False, updates are applied in a single atomic transaction.

    Args:
        path: Path to invocations SQLite file. If None, resolves default platform path.
        dry_run: If True, reports discrepancies without modifying database.

    Returns:
        ReconciliationReport with count of mismatches and corrections applied.

    Raises:
        FileNotFoundError: If database file does not exist.
    """
    if path is None:
        target_path = resolve_invocation_db_path(create=False)
    else:
        target_path = Path(path).resolve()

    if not target_path.is_file():
        raise FileNotFoundError(f"Invocation database not found at {target_path}")

    conn = sqlite3.connect(str(target_path), timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 15000;")

    details: List[str] = []
    actions_to_apply: List[Tuple[str, Tuple[Any, ...]]] = []

    try:
        # 1. Reconcile program_usage
        expected_prog_rows = conn.execute(
            """
            SELECT
                program_id,
                COUNT(*) AS total_starts,
                COUNT(CASE WHEN status = 'exited' AND exit_code = 0 THEN 1 END) AS success_count,
                COUNT(CASE WHEN (exit_code IS NOT NULL AND exit_code != 0) OR status IN ('launch_failed', 'interrupted') THEN 1 END) AS failure_count,
                COUNT(CASE WHEN status NOT IN ('started') AND NOT (status = 'exited' AND exit_code = 0) AND NOT ((exit_code IS NOT NULL AND exit_code != 0) OR status IN ('launch_failed', 'interrupted')) THEN 1 END) AS unknown_count,
                MIN(started_at_utc) AS first_seen_utc,
                MAX(COALESCE(finished_at_utc, started_at_utc)) AS last_seen_utc
            FROM invocations
            GROUP BY program_id
            """
        ).fetchall()
        expected_progs: Dict[str, Dict[str, Any]] = {r["program_id"]: dict(r) for r in expected_prog_rows}

        current_prog_rows = conn.execute("SELECT * FROM program_usage").fetchall()
        current_progs: Dict[str, Dict[str, Any]] = {r["program_id"]: dict(r) for r in current_prog_rows}

        for prog_id, exp in expected_progs.items():
            if prog_id not in current_progs:
                details.append(f"program_usage '{prog_id}': missing row (expected starts={exp['total_starts']})")
                actions_to_apply.append(
                    (
                        """
                        INSERT INTO program_usage (
                            program_id, total_starts, success_count, failure_count, unknown_count,
                            first_seen_utc, last_seen_utc
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            prog_id,
                            exp["total_starts"],
                            exp["success_count"],
                            exp["failure_count"],
                            exp["unknown_count"],
                            exp["first_seen_utc"],
                            exp["last_seen_utc"],
                        ),
                    )
                )
            else:
                cur = current_progs[prog_id]
                diffs = []
                for col in ("total_starts", "success_count", "failure_count", "unknown_count", "first_seen_utc", "last_seen_utc"):
                    if cur[col] != exp[col]:
                        diffs.append(f"{col} expected {exp[col]}, found {cur[col]}")
                if diffs:
                    details.append(f"program_usage '{prog_id}': {'; '.join(diffs)}")
                    actions_to_apply.append(
                        (
                            """
                            UPDATE program_usage
                            SET total_starts = ?, success_count = ?, failure_count = ?, unknown_count = ?,
                                first_seen_utc = ?, last_seen_utc = ?
                            WHERE program_id = ?
                            """,
                            (
                                exp["total_starts"],
                                exp["success_count"],
                                exp["failure_count"],
                                exp["unknown_count"],
                                exp["first_seen_utc"],
                                exp["last_seen_utc"],
                                prog_id,
                            ),
                        )
                    )

        for prog_id in current_progs:
            if prog_id not in expected_progs:
                details.append(f"program_usage '{prog_id}': orphan row not present in invocations")
                actions_to_apply.append(
                    ("DELETE FROM program_usage WHERE program_id = ?", (prog_id,))
                )

        # 2. Reconcile command_patterns
        expected_pattern_rows = conn.execute(
            """
            SELECT
                pattern_id,
                program_id,
                MIN(redacted_argv_json) AS pattern_argv_json,
                COUNT(*) AS invocation_count,
                COUNT(CASE WHEN status = 'exited' AND exit_code = 0 THEN 1 END) AS success_count,
                COUNT(CASE WHEN (exit_code IS NOT NULL AND exit_code != 0) OR status IN ('launch_failed', 'interrupted') THEN 1 END) AS failure_count,
                COUNT(CASE WHEN status NOT IN ('started') AND NOT (status = 'exited' AND exit_code = 0) AND NOT ((exit_code IS NOT NULL AND exit_code != 0) OR status IN ('launch_failed', 'interrupted')) THEN 1 END) AS unknown_count,
                MIN(started_at_utc) AS first_seen_utc,
                MAX(COALESCE(finished_at_utc, started_at_utc)) AS last_seen_utc
            FROM invocations
            GROUP BY pattern_id
            """
        ).fetchall()
        expected_patterns: Dict[str, Dict[str, Any]] = {r["pattern_id"]: dict(r) for r in expected_pattern_rows}

        current_pattern_rows = conn.execute("SELECT * FROM command_patterns").fetchall()
        current_patterns: Dict[str, Dict[str, Any]] = {r["pattern_id"]: dict(r) for r in current_pattern_rows}

        for pat_id, exp in expected_patterns.items():
            if pat_id not in current_patterns:
                details.append(f"command_patterns '{pat_id}': missing row (expected invocations={exp['invocation_count']})")
                actions_to_apply.append(
                    (
                        """
                        INSERT INTO command_patterns (
                            pattern_id, program_id, pattern_argv_json,
                            invocation_count, success_count, failure_count, unknown_count,
                            first_seen_utc, last_seen_utc
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            pat_id,
                            exp["program_id"],
                            exp["pattern_argv_json"],
                            exp["invocation_count"],
                            exp["success_count"],
                            exp["failure_count"],
                            exp["unknown_count"],
                            exp["first_seen_utc"],
                            exp["last_seen_utc"],
                        ),
                    )
                )
            else:
                cur = current_patterns[pat_id]
                diffs = []
                for col in ("invocation_count", "success_count", "failure_count", "unknown_count", "first_seen_utc", "last_seen_utc", "pattern_argv_json", "program_id"):
                    if cur[col] != exp[col]:
                        diffs.append(f"{col} expected {exp[col]}, found {cur[col]}")
                if diffs:
                    details.append(f"command_patterns '{pat_id}': {'; '.join(diffs)}")
                    actions_to_apply.append(
                        (
                            """
                            UPDATE command_patterns
                            SET program_id = ?, pattern_argv_json = ?,
                                invocation_count = ?, success_count = ?, failure_count = ?, unknown_count = ?,
                                first_seen_utc = ?, last_seen_utc = ?
                            WHERE pattern_id = ?
                            """,
                            (
                                exp["program_id"],
                                exp["pattern_argv_json"],
                                exp["invocation_count"],
                                exp["success_count"],
                                exp["failure_count"],
                                exp["unknown_count"],
                                exp["first_seen_utc"],
                                exp["last_seen_utc"],
                                pat_id,
                            ),
                        )
                    )

        for pat_id in current_patterns:
            if pat_id not in expected_patterns:
                details.append(f"command_patterns '{pat_id}': orphan row not present in invocations")
                actions_to_apply.append(
                    ("DELETE FROM command_patterns WHERE pattern_id = ?", (pat_id,))
                )

        # 3. Reconcile alias_usage
        expected_alias_rows = conn.execute(
            """
            SELECT
                invoked_name,
                program_id,
                COUNT(*) AS total_starts,
                COUNT(CASE WHEN status = 'exited' AND exit_code = 0 THEN 1 END) AS success_count,
                COUNT(CASE WHEN (exit_code IS NOT NULL AND exit_code != 0) OR status IN ('launch_failed', 'interrupted') THEN 1 END) AS failure_count,
                COUNT(CASE WHEN status NOT IN ('started') AND NOT (status = 'exited' AND exit_code = 0) AND NOT ((exit_code IS NOT NULL AND exit_code != 0) OR status IN ('launch_failed', 'interrupted')) THEN 1 END) AS unknown_count,
                MIN(started_at_utc) AS first_seen_utc,
                MAX(COALESCE(finished_at_utc, started_at_utc)) AS last_seen_utc
            FROM invocations
            GROUP BY invoked_name, program_id
            """
        ).fetchall()
        expected_aliases: Dict[Tuple[str, str], Dict[str, Any]] = {
            (r["invoked_name"], r["program_id"]): dict(r) for r in expected_alias_rows
        }

        current_alias_rows = conn.execute("SELECT * FROM alias_usage").fetchall()
        current_aliases: Dict[Tuple[str, str], Dict[str, Any]] = {
            (r["invoked_name"], r["program_id"]): dict(r) for r in current_alias_rows
        }

        for (name, prog_id), exp in expected_aliases.items():
            key = (name, prog_id)
            if key not in current_aliases:
                details.append(f"alias_usage '{name}' -> '{prog_id}': missing row")
                actions_to_apply.append(
                    (
                        """
                        INSERT INTO alias_usage (
                            invoked_name, program_id, total_starts, success_count, failure_count,
                            unknown_count, first_seen_utc, last_seen_utc
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            name,
                            prog_id,
                            exp["total_starts"],
                            exp["success_count"],
                            exp["failure_count"],
                            exp["unknown_count"],
                            exp["first_seen_utc"],
                            exp["last_seen_utc"],
                        ),
                    )
                )
            else:
                cur = current_aliases[key]
                diffs = []
                for col in ("total_starts", "success_count", "failure_count", "unknown_count", "first_seen_utc", "last_seen_utc"):
                    if cur[col] != exp[col]:
                        diffs.append(f"{col} expected {exp[col]}, found {cur[col]}")
                if diffs:
                    details.append(f"alias_usage '{name}' -> '{prog_id}': {'; '.join(diffs)}")
                    actions_to_apply.append(
                        (
                            """
                            UPDATE alias_usage
                            SET total_starts = ?, success_count = ?, failure_count = ?, unknown_count = ?,
                                first_seen_utc = ?, last_seen_utc = ?
                            WHERE invoked_name = ? AND program_id = ?
                            """,
                            (
                                exp["total_starts"],
                                exp["success_count"],
                                exp["failure_count"],
                                exp["unknown_count"],
                                exp["first_seen_utc"],
                                exp["last_seen_utc"],
                                name,
                                prog_id,
                            ),
                        )
                    )

        for (name, prog_id) in current_aliases:
            if (name, prog_id) not in expected_aliases:
                details.append(f"alias_usage '{name}' -> '{prog_id}': orphan row not present in invocations")
                actions_to_apply.append(
                    ("DELETE FROM alias_usage WHERE invoked_name = ? AND program_id = ?", (name, prog_id))
                )

        mismatches_found = len(details)
        corrections_applied = 0

        if not dry_run and actions_to_apply:
            with conn:
                for sql, params in actions_to_apply:
                    conn.execute(sql, params)
            corrections_applied = mismatches_found

        return ReconciliationReport(
            mismatches_found=mismatches_found,
            corrections_applied=corrections_applied,
            details=tuple(details),
        )
    finally:
        conn.close()
