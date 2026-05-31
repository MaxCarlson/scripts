import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path, PurePosixPath
from typing import Optional


LEASE_MINUTES = 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _expires() -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=LEASE_MINUTES)
    return exp.isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalise(path: Path) -> str:
    """Return a repo-relative POSIX string without leading slash."""
    return str(PurePosixPath(path)).lstrip("/")


class ClaimConflictError(Exception):
    pass


@dataclass
class Claim:
    claim_id: str
    run_id: str
    task_id: str
    repo_root: str
    path: str
    path_kind: str
    access_mode: str
    lease_expires_at: str
    created_at: str
    released_at: Optional[str] = None


def check_conflicts(
    conn: sqlite3.Connection,
    *,
    repo_root: Path,
    paths: list[Path],
    access_mode: str = "write",
) -> list[dict]:
    """Return active conflicting write claims for the given paths.

    Only write-access conflicts are checked. Two read claims on the same path
    do not conflict with each other.
    """
    if access_mode != "write":
        return []
    root = str(repo_root)
    now = _now()
    conflicts = []
    for path in paths:
        candidate = _normalise(path)
        rows = conn.execute(
            """
            SELECT claim_id, run_id, path
            FROM claims
            WHERE repo_root = ?
              AND access_mode = 'write'
              AND released_at IS NULL
              AND lease_expires_at > ?
              AND (
                    path = ?
                 OR path LIKE ? || '/%'
                 OR ? LIKE path || '/%'
              )
            LIMIT 1
            """,
            (root, now, candidate, candidate, candidate),
        ).fetchall()
        conflicts.extend(dict(r) for r in rows)
    return conflicts


def acquire_claims(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    task_id: str,
    repo_root: Path,
    paths: list[Path],
    access_mode: str = "write",
) -> list[str]:
    """Acquire file-level leases inside a BEGIN IMMEDIATE transaction.

    Raises ClaimConflictError if a write conflict exists for any path.
    Returns list of claim IDs on success.
    """
    if access_mode == "write":
        conflicts = check_conflicts(conn, repo_root=repo_root, paths=paths)
        if conflicts:
            raise ClaimConflictError(
                f"Write conflict on paths: {[c['path'] for c in conflicts]}"
            )

    root = str(repo_root)
    now = _now()
    expires = _expires()
    claim_ids = []

    conn.execute("BEGIN IMMEDIATE")
    try:
        for path in paths:
            normalised = _normalise(path)
            kind = "dir" if str(path).endswith("/") else "file"
            cid = f"CLM-{uuid.uuid4().hex[:10]}"
            conn.execute(
                """
                INSERT INTO claims
                  (claim_id, run_id, task_id, repo_root, path, path_kind,
                   access_mode, lease_expires_at, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (cid, run_id, task_id, root, normalised, kind,
                 access_mode, expires, now),
            )
            claim_ids.append(cid)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return claim_ids


def release_claims(conn: sqlite3.Connection, run_id: str) -> None:
    """Release all active claims for the given run."""
    conn.execute(
        "UPDATE claims SET released_at=? WHERE run_id=? AND released_at IS NULL",
        (_now(), run_id),
    )
    conn.commit()
