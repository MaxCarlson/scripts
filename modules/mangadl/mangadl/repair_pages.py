"""Archive-aware, page-targeted repair for uniquely identified nhentai galleries."""

from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .destination_audit import _validate_image

_PAGE_NAME = re.compile(r"^(?P<page>\d+)\.(?P<extension>[^.]+)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PageRepairPlan:
    url: str
    folder: Path
    expected_count: int
    damaged_pages: tuple[int, ...]
    page_keys: dict[int, str]
    corrupt_files: tuple[Path, ...]
    archive_rows_found: tuple[str, ...]
    archive_table: str | None

    @property
    def eligible(self) -> bool:
        return bool(self.damaged_pages) and set(self.page_keys) == set(range(1, self.expected_count + 1))


def repair_confirmation_token(plan: PageRepairPlan) -> str:
    """Bind apply confirmation to the exact previewed repair targets."""
    payload = {
        "url": plan.url,
        "folder": str(plan.folder.resolve()),
        "expected_count": plan.expected_count,
        "damaged_pages": list(plan.damaged_pages),
        "page_keys": {str(page): plan.page_keys[page] for page in plan.damaged_pages},
        "corrupt_files": [str(path.resolve()) for path in plan.corrupt_files],
        "archive_rows_found": list(plan.archive_rows_found),
        "archive_table": plan.archive_table,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return digest[:16]


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _archive_rows(path: Path, keys: set[str]) -> tuple[str | None, set[str]]:
    if not path.is_file():
        return None, set()
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    try:
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        matches: list[tuple[str, set[str]]] = []
        entry_tables: list[str] = []
        for (table,) in tables:
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({_quote(table)})")}
            if "entry" not in columns:
                continue
            entry_tables.append(str(table))
            placeholders = ",".join("?" for _ in keys)
            if not placeholders:
                continue
            found = {
                str(row[0])
                for row in connection.execute(
                    f"SELECT entry FROM {_quote(table)} WHERE entry IN ({placeholders})", tuple(keys)
                )
            }
            if found:
                matches.append((str(table), found))
        if len(matches) > 1:
            raise ValueError("target archive keys span multiple tables; refusing ambiguous repair")
        if matches:
            return matches[0]
        if "archive" in entry_tables:
            return "archive", set()
        if len(entry_tables) == 1:
            return entry_tables[0], set()
        if len(entry_tables) > 1:
            raise ValueError("archive table is ambiguous; refusing targeted repair")
        return None, set()
    finally:
        connection.close()


def make_page_repair_plan(
    url: str,
    folder: Path,
    expected_count: int,
    missing_pages: list[int],
    corrupt_files: list[str],
    page_keys: dict[int, str],
    archive: Path,
) -> PageRepairPlan:
    if expected_count < 1 or expected_count > 20_000:
        raise ValueError("expected page count is outside the supported repair bounds")
    pages = tuple(sorted(set(int(page) for page in missing_pages)))
    if any(page < 1 or page > expected_count for page in pages):
        raise ValueError("audit returned a page outside the expected page set")
    keys = {int(page): str(key) for page, key in page_keys.items()}
    corrupt_paths = tuple((folder / relative).resolve() for relative in corrupt_files)
    for path in corrupt_paths:
        if path.parent != folder.resolve() or not path.is_file() or _validate_image(path):
            raise ValueError(f"corrupt-page target changed or is not a direct gallery image: {path}")
    target_keys = {keys[page] for page in pages if page in keys}
    table, found = _archive_rows(archive, target_keys)
    return PageRepairPlan(
        url=url,
        folder=folder,
        expected_count=expected_count,
        damaged_pages=pages,
        page_keys=keys,
        corrupt_files=corrupt_paths,
        archive_rows_found=tuple(sorted(found)),
        archive_table=table,
    )


def _snapshot_archive(archive: Path, backup: Path) -> None:
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not archive.is_file():
        return
    source = sqlite3.connect(str(archive), timeout=30)
    target = sqlite3.connect(str(backup), timeout=30)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _update_archive_keys(archive: Path, table: str, values: dict[str, bool]) -> None:
    if not values:
        return
    archive.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(archive), timeout=30, isolation_level=None)
    try:
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS {_quote(table)} (entry TEXT PRIMARY KEY) WITHOUT ROWID"
        )
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({_quote(table)})")}
        if "entry" not in columns:
            raise ValueError(f"gallery-dl archive table has no entry column: {table}")
        connection.execute("BEGIN IMMEDIATE")
        for key, should_exist in values.items():
            if should_exist:
                connection.execute(f"INSERT OR IGNORE INTO {_quote(table)} (entry) VALUES (?)", (key,))
            else:
                connection.execute(f"DELETE FROM {_quote(table)} WHERE entry=?", (key,))
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def apply_page_repair(
    plan: PageRepairPlan,
    archive: Path,
    quarantine_root: Path,
    run_download,
    verify_repair,
) -> dict[str, Any]:
    """Run a normal one-worker targeted download and reconcile only its keys."""
    if not plan.eligible:
        raise ValueError("repair plan is not eligible; expected page identities are incomplete")
    if len(plan.damaged_pages) > 1000:
        raise ValueError("one repair apply is limited to 1000 pages; split the reviewed repair into smaller plans")
    repair_id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)
    control_root = archive.parent
    backup = control_root / "archive-backups" / f"repair-{repair_id}.sqlite3"
    _snapshot_archive(archive, backup)
    quarantine = quarantine_root / repair_id / plan.folder.name
    moved: list[tuple[Path, Path]] = []
    lock = control_root / "repair.lock"
    token = secrets.token_hex(24)
    lock.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, token.encode("ascii"))
    finally:
        os.close(descriptor)
    try:
        for source in plan.corrupt_files:
            quarantine.mkdir(parents=True, exist_ok=True)
            target = quarantine / source.name
            if target.exists():
                raise ValueError(f"quarantine target already exists: {target}")
            shutil.move(str(source), str(target))
            moved.append((source, target))
        if plan.archive_table and plan.archive_rows_found:
            _update_archive_keys(archive, plan.archive_table, {key: False for key in plan.archive_rows_found})
        (quarantine / "repair-manifest.json").write_text(
            json.dumps(
                {
                    "repair_id": repair_id,
                    "source_url": plan.url,
                    "folder": str(plan.folder),
                    "expected_pages": plan.expected_count,
                    "target_pages": list(plan.damaged_pages),
                    "archive_backup": str(backup) if backup.exists() else None,
                    "quarantined_files": [str(target) for _source, target in moved],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        run_error = None
        try:
            run_download(",".join(str(page) for page in plan.damaged_pages), token)
        except Exception as exc:
            run_error = f"{type(exc).__name__}: {exc}"
        try:
            verified, remaining = verify_repair()
        except Exception as exc:
            verified = False
            remaining = set(plan.damaged_pages)
            run_error = run_error or f"post-repair audit failed: {type(exc).__name__}: {exc}"
        table = plan.archive_table or "archive"
        key_states = {
            plan.page_keys[page]: page not in remaining
            for page in plan.damaged_pages
            if page in plan.page_keys
        }
        _update_archive_keys(archive, table, key_states)
        return {
            "repair_id": repair_id,
            "verified": bool(verified and run_error is None),
            "remaining_pages": sorted(remaining),
            "run_error": run_error,
            "archive_backup": str(backup) if backup.exists() else None,
            "quarantine": str(quarantine),
            "archive_reconciled_pages": sorted(page for page in plan.damaged_pages if page not in remaining),
        }
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
