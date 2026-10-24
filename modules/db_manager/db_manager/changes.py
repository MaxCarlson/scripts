"""
changes.py — Conservative, transactional editing, schema initialization, and database comparison.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any

from db_manager.backup import backup_database
from db_manager.connections import get_readonly_connection, get_write_connection
from db_manager.inspector import get_schema
from db_manager.query import get_table_columns, quote_identifier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InitPlan:
    target_path: str
    schema_sql: str | None
    statements: list[str]
    is_dry_run: bool


@dataclass(frozen=True)
class EditPlan:
    table: str
    pk_values: dict[str, Any]
    old_values: dict[str, Any]
    new_values: dict[str, Any]
    sql: str
    params: list[Any]
    is_dry_run: bool
    backup_path: str | None = None


@dataclass(frozen=True)
class InsertPlan:
    table: str
    values: dict[str, Any]
    sql: str
    params: list[Any]
    is_dry_run: bool
    backup_path: str | None = None


@dataclass(frozen=True)
class DeletePlan:
    table: str
    pk_values: dict[str, Any]
    deleted_row: dict[str, Any]
    sql: str
    params: list[Any]
    is_dry_run: bool
    backup_path: str | None = None


@dataclass(frozen=True)
class MutationResult:
    sql: str
    affected_rows: int
    is_dry_run: bool
    backup_path: str | None = None


@dataclass(frozen=True)
class DatabaseComparison:
    db1_path: str
    db2_path: str
    schema_differences: list[str]
    table_comparisons: list[dict[str, Any]]
    identical: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_key_value_spec(spec: str) -> dict[str, Any]:
    """
    Parses key-value specifications from either JSON string or comma-separated key=value pairs.
    Example: 'id=42,status=active' or '{"id": 42, "status": "active"}'
    """
    trimmed = spec.strip()
    if trimmed.startswith("{") and trimmed.endswith("}"):
        return json.loads(trimmed)

    result: dict[str, Any] = {}
    for item in trimmed.split(","):
        if not item.strip():
            continue
        if "=" not in item:
            raise ValueError(f"Invalid key=value pair: '{item}'")
        k, v = item.split("=", 1)
        k = k.strip()
        v = v.strip()

        # Coerce numeric/boolean/null values
        if v.lower() == "null":
            val = None
        elif v.lower() == "true":
            val = True
        elif v.lower() == "false":
            val = False
        elif re.match(r"^-?\d+$", v):
            val = int(v)
        elif re.match(r"^-?\d+\.\d+$", v):
            val = float(v)
        else:
            # Strip surrounding quotes if present
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                val = v[1:-1]
            else:
                val = v

        result[k] = val

    return result


def init_database(
    db_path: str | Path,
    schema_sql: str | None = None,
    dry_run: bool = True,
    force: bool = False,
) -> InitPlan:
    """
    Initializes a new empty SQLite database or applies user-supplied schema SQL.
    Does not initialize or migrate application-specific schemas (e.g. script_logging).
    """
    path = Path(db_path).resolve()
    if path.exists() and not force:
        raise FileExistsError(f"Target database already exists: {path}. Use force (-f/--force) to overwrite.")

    statements: list[str] = []
    if schema_sql:
        # Split statements cleanly on semicolon followed by whitespace/end
        raw_stmts = [s.strip() for s in schema_sql.split(";") if s.strip()]
        statements = raw_stmts

    if dry_run:
        return InitPlan(
            target_path=str(path),
            schema_sql=schema_sql,
            statements=statements,
            is_dry_run=True,
        )

    # Perform creation
    if path.exists() and force:
        path.unlink()

    path.parent.mkdir(parents=True, exist_ok=True)
    with get_write_connection(path, create_if_missing=True) as conn:
        for stmt in statements:
            conn.execute(stmt)

    return InitPlan(
        target_path=str(path),
        schema_sql=schema_sql,
        statements=statements,
        is_dry_run=False,
    )


def plan_and_apply_edit(
    db_path: str | Path,
    table: str,
    pk_values: dict[str, Any],
    new_values: dict[str, Any],
    dry_run: bool = True,
    skip_backup: bool = False,
    expected_old_values: dict[str, Any] | None = None,
) -> EditPlan:
    """
    Inspects a single row by primary key and applies modifications with optimistic concurrency checks.
    Requires all originally observed values to match using NULL-safe comparisons so unrelated
    matching columns cannot bypass conflict detection.
    Aborts if exactly one row was not affected.
    """
    path = Path(db_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Database file not found: {path}")

    # Inspect current row under read-only connection
    with get_readonly_connection(path) as ro_conn:
        valid_cols = get_table_columns(ro_conn, table)
        for col in list(pk_values.keys()) + list(new_values.keys()):
            if col not in valid_cols:
                raise ValueError(f"Unknown column '{col}' in table '{table}'")

        quoted_table = quote_identifier(table)
        pk_where = " AND ".join(f"{quote_identifier(k)} = ?" for k in pk_values.keys())
        pk_params = list(pk_values.values())

        query = f"SELECT * FROM {quoted_table} WHERE {pk_where}"
        rows = ro_conn.execute(query, pk_params).fetchall()
        if len(rows) == 0:
            raise ValueError(f"No row matches primary key {pk_values} in table '{table}'")
        if len(rows) > 1:
            raise ValueError(f"Ambiguous primary key: matches {len(rows)} rows in table '{table}'")

        old_row = dict(rows[0])

    if expected_old_values is not None:
        for k, exp_val in expected_old_values.items():
            if old_row.get(k) != exp_val:
                raise RuntimeError(
                    f"Optimistic concurrency violation: column '{k}' has changed from '{exp_val}' to '{old_row.get(k)}'. "
                    "Transaction aborted."
                )

    target_values = expected_old_values if expected_old_values is not None else old_row

    # Build optimistic concurrency UPDATE query requiring all observed columns to match
    set_clause = ", ".join(f"{quote_identifier(k)} = ?" for k in new_values.keys())
    set_params = list(new_values.values())

    concurrency_clauses = []
    concurrency_params: list[Any] = []
    for k, old_val in target_values.items():
        quoted_col = quote_identifier(k)
        if old_val is None:
            concurrency_clauses.append(f"{quoted_col} IS NULL")
        else:
            concurrency_clauses.append(f"{quoted_col} = ?")
            concurrency_params.append(old_val)

    concurrency_where = " AND ".join(concurrency_clauses)
    update_sql = f"UPDATE {quoted_table} SET {set_clause} WHERE {concurrency_where}"
    total_params = set_params + concurrency_params

    backup_file: str | None = None

    if dry_run:
        return EditPlan(
            table=table,
            pk_values=pk_values,
            old_values=old_row,
            new_values=new_values,
            sql=update_sql,
            params=total_params,
            is_dry_run=True,
        )

    # Perform pre-write backup before modifying
    if not skip_backup:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        bak_path = path.parent / f"{path.name}.pre-edit-{ts}.bak"
        backup_database(path, bak_path, force=True, write_manifest=True)
        backup_file = str(bak_path)

    # Execute atomic transactional update
    with get_write_connection(path, enforce_foreign_keys=True) as w_conn:
        cur = w_conn.execute(update_sql, total_params)
        if cur.rowcount != 1:
            raise RuntimeError(
                f"Optimistic concurrency violation: expected to update 1 row, but affected {cur.rowcount}. "
                "The row was modified or deleted concurrently. Transaction rolled back."
            )

    return EditPlan(
        table=table,
        pk_values=pk_values,
        old_values=old_row,
        new_values=new_values,
        sql=update_sql,
        params=total_params,
        is_dry_run=False,
        backup_path=backup_file,
    )


def plan_and_apply_insert(
    db_path: str | Path,
    table: str,
    values: dict[str, Any],
    dry_run: bool = True,
    skip_backup: bool = False,
) -> InsertPlan:
    """
    Inserts a single row with column validation and foreign key enforcement.
    """
    path = Path(db_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Database file not found: {path}")

    with get_readonly_connection(path) as ro_conn:
        valid_cols = get_table_columns(ro_conn, table)
        for col in values.keys():
            if col not in valid_cols:
                raise ValueError(f"Unknown column '{col}' in table '{table}'")

    quoted_table = quote_identifier(table)
    col_names = ", ".join(quote_identifier(k) for k in values.keys())
    placeholders = ", ".join("?" for _ in values)
    sql = f"INSERT INTO {quoted_table} ({col_names}) VALUES ({placeholders})"
    params = list(values.values())

    backup_file: str | None = None
    if dry_run:
        return InsertPlan(
            table=table,
            values=values,
            sql=sql,
            params=params,
            is_dry_run=True,
        )

    if not skip_backup:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        bak_path = path.parent / f"{path.name}.pre-insert-{ts}.bak"
        backup_database(path, bak_path, force=True, write_manifest=True)
        backup_file = str(bak_path)

    with get_write_connection(path, enforce_foreign_keys=True) as w_conn:
        cur = w_conn.execute(sql, params)
        if cur.rowcount != 1:
            raise RuntimeError(f"Insert failed to affect 1 row (rowcount: {cur.rowcount}). Transaction rolled back.")

    return InsertPlan(
        table=table,
        values=values,
        sql=sql,
        params=params,
        is_dry_run=False,
        backup_path=backup_file,
    )


def plan_and_apply_delete(
    db_path: str | Path,
    table: str,
    pk_values: dict[str, Any],
    dry_run: bool = True,
    skip_backup: bool = False,
    expected_old_values: dict[str, Any] | None = None,
) -> DeletePlan:
    """
    Deletes a single row by primary key with optimistic concurrency check.
    Requires all originally observed values to match using NULL-safe comparisons so unrelated
    matching columns cannot bypass conflict detection.
    Aborts if exactly one row was not affected.
    """
    path = Path(db_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Database file not found: {path}")

    with get_readonly_connection(path) as ro_conn:
        valid_cols = get_table_columns(ro_conn, table)
        for col in pk_values.keys():
            if col not in valid_cols:
                raise ValueError(f"Unknown column '{col}' in table '{table}'")

        quoted_table = quote_identifier(table)
        pk_where = " AND ".join(f"{quote_identifier(k)} = ?" for k in pk_values.keys())
        pk_params = list(pk_values.values())

        query = f"SELECT * FROM {quoted_table} WHERE {pk_where}"
        rows = ro_conn.execute(query, pk_params).fetchall()
        if len(rows) == 0:
            raise ValueError(f"No row matches primary key {pk_values} in table '{table}'")
        if len(rows) > 1:
            raise ValueError(f"Ambiguous primary key: matches {len(rows)} rows in table '{table}'")

        deleted_row = dict(rows[0])

    if expected_old_values is not None:
        for k, exp_val in expected_old_values.items():
            if deleted_row.get(k) != exp_val:
                raise RuntimeError(
                    f"Optimistic concurrency violation: column '{k}' has changed from '{exp_val}' to '{deleted_row.get(k)}'. "
                    "Transaction aborted."
                )

    target_values = expected_old_values if expected_old_values is not None else deleted_row

    # Build optimistic concurrency DELETE query requiring all observed columns to match
    concurrency_clauses = []
    concurrency_params: list[Any] = []
    for k, old_val in target_values.items():
        quoted_col = quote_identifier(k)
        if old_val is None:
            concurrency_clauses.append(f"{quoted_col} IS NULL")
        else:
            concurrency_clauses.append(f"{quoted_col} = ?")
            concurrency_params.append(old_val)

    concurrency_where = " AND ".join(concurrency_clauses)
    delete_sql = f"DELETE FROM {quoted_table} WHERE {concurrency_where}"
    backup_file: str | None = None

    if dry_run:
        return DeletePlan(
            table=table,
            pk_values=pk_values,
            deleted_row=deleted_row,
            sql=delete_sql,
            params=concurrency_params,
            is_dry_run=True,
        )

    if not skip_backup:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        bak_path = path.parent / f"{path.name}.pre-delete-{ts}.bak"
        backup_database(path, bak_path, force=True, write_manifest=True)
        backup_file = str(bak_path)

    with get_write_connection(path, enforce_foreign_keys=True) as w_conn:
        cur = w_conn.execute(delete_sql, concurrency_params)
        if cur.rowcount != 1:
            raise RuntimeError(
                f"Optimistic concurrency violation: expected to delete 1 row, but affected {cur.rowcount}. "
                "The row was modified or deleted concurrently. Transaction rolled back."
            )

    return DeletePlan(
        table=table,
        pk_values=pk_values,
        deleted_row=deleted_row,
        sql=delete_sql,
        params=concurrency_params,
        is_dry_run=False,
        backup_path=backup_file,
    )


def execute_mutation_sql(
    db_path: str | Path,
    sql: str,
    params: tuple[Any, ...] | dict[str, Any] = (),
    dry_run: bool = True,
    skip_backup: bool = False,
) -> MutationResult:
    """
    Executes user-supplied mutation SQL requiring explicit -w/--write.
    Rejects ATTACH/DETACH and dangerous pragmas via write_authorizer.
    """
    path = Path(db_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Database file not found: {path}")

    cleaned = sql.strip()
    if not cleaned:
        raise ValueError("SQL string cannot be empty")

    backup_file: str | None = None

    if dry_run:
        return MutationResult(
            sql=sql,
            affected_rows=0,
            is_dry_run=True,
        )

    if not skip_backup:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        bak_path = path.parent / f"{path.name}.pre-sql-{ts}.bak"
        backup_database(path, bak_path, force=True, write_manifest=True)
        backup_file = str(bak_path)

    with get_write_connection(path, enforce_foreign_keys=True) as w_conn:
        cur = w_conn.execute(cleaned, params)
        affected = cur.rowcount

    return MutationResult(
        sql=sql,
        affected_rows=affected,
        is_dry_run=False,
        backup_path=backup_file,
    )


def compare_databases(db1_path: str | Path, db2_path: str | Path, row_limit: int = 50) -> DatabaseComparison:
    """
    Compares schema definitions and table row counts/keys between two independent SQLite databases.
    """
    p1 = Path(db1_path).resolve()
    p2 = Path(db2_path).resolve()

    if not p1.exists():
        raise FileNotFoundError(f"First database not found: {p1}")
    if not p2.exists():
        raise FileNotFoundError(f"Second database not found: {p2}")

    with get_readonly_connection(p1) as conn1, get_readonly_connection(p2) as conn2:
        schema1 = {s.name: s for s in get_schema(conn1)}
        schema2 = {s.name: s for s in get_schema(conn2)}

        diffs: list[str] = []
        table_reports: list[dict[str, Any]] = []

        all_tables = sorted(set(schema1.keys()) | set(schema2.keys()))

        for tbl in all_tables:
            in_1 = tbl in schema1
            in_2 = tbl in schema2

            if in_1 and not in_2:
                diffs.append(f"Table '{tbl}' exists in {p1.name} but missing in {p2.name}")
                table_reports.append({"table": tbl, "status": "only_in_db1"})
                continue
            if in_2 and not in_1:
                diffs.append(f"Table '{tbl}' exists in {p2.name} but missing in {p1.name}")
                table_reports.append({"table": tbl, "status": "only_in_db2"})
                continue

            s1 = schema1[tbl]
            s2 = schema2[tbl]

            # Compare columns
            cols1 = {c.name: c.type for c in s1.columns}
            cols2 = {c.name: c.type for c in s2.columns}
            col_diffs = []
            for c, t in cols1.items():
                if c not in cols2:
                    col_diffs.append(f"column '{c}' missing in db2")
                elif cols2[c] != t:
                    col_diffs.append(f"column '{c}' type mismatch: {t} vs {cols2[c]}")
            for c in cols2:
                if c not in cols1:
                    col_diffs.append(f"column '{c}' missing in db1")

            if col_diffs:
                diffs.append(f"Table '{tbl}' column differences: {'; '.join(col_diffs)}")

            # Row count check
            cnt1 = conn1.execute(f"SELECT COUNT(*) FROM {quote_identifier(tbl)}").fetchone()[0]
            cnt2 = conn2.execute(f"SELECT COUNT(*) FROM {quote_identifier(tbl)}").fetchone()[0]

            count_match = cnt1 == cnt2
            if not count_match:
                diffs.append(f"Table '{tbl}' row count mismatch: {cnt1} vs {cnt2}")

            # Keyed row comparison when primary key exists
            pk_cols = [c.name for c in s1.columns if c.pk > 0]
            row_diffs: list[str] = []
            if pk_cols and not col_diffs:
                rows1 = {
                    tuple(r[k] for k in pk_cols): dict(r)
                    for r in conn1.execute(f"SELECT * FROM {quote_identifier(tbl)} LIMIT ?", (row_limit,)).fetchall()
                }
                rows2 = {
                    tuple(r[k] for k in pk_cols): dict(r)
                    for r in conn2.execute(f"SELECT * FROM {quote_identifier(tbl)} LIMIT ?", (row_limit,)).fetchall()
                }
                for pk, r1_data in rows1.items():
                    if pk in rows2:
                        r2_data = rows2[pk]
                        field_diffs = [f for f in r1_data if f in r2_data and r1_data[f] != r2_data[f]]
                        if field_diffs:
                            row_diffs.append(f"Table '{tbl}' row PK={pk} differs in: {', '.join(field_diffs)}")
                    else:
                        row_diffs.append(f"Table '{tbl}' row PK={pk} in db1 missing in db2")
                for pk in rows2:
                    if pk not in rows1:
                        row_diffs.append(f"Table '{tbl}' row PK={pk} in db2 missing in db1")

                if row_diffs:
                    diffs.extend(row_diffs[:20])

            table_reports.append(
                {
                    "table": tbl,
                    "status": "match" if (not col_diffs and count_match and not row_diffs) else "differ",
                    "db1_row_count": cnt1,
                    "db2_row_count": cnt2,
                    "column_differences": col_diffs,
                    "row_differences": row_diffs,
                }
            )

    identical = len(diffs) == 0

    return DatabaseComparison(
        db1_path=str(p1),
        db2_path=str(p2),
        schema_differences=diffs,
        table_comparisons=table_reports,
        identical=identical,
    )
