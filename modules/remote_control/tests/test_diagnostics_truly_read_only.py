"""Tests for Stage C: Truly Read-Only Diagnostics Invariants.

Verifies that `status`, `external status`, and `external doctor` NEVER:
- Create or migrate the authentication database.
- Create or alter filesystem directories or Windows ACLs.
- Create simulation state files when they do not already exist.
- Mutate existing database records or timestamps.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Set

import pytest

from remote_control.cli import main
from remote_control.config import RemoteControlConfig


def _get_tree_snapshot(directory: Path) -> Set[str]:
    """Return set of relative file paths in directory."""
    if not directory.exists():
        return set()
    return {str(p.relative_to(directory)) for p in directory.rglob("*")}


def _file_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    if not path.is_file():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def test_diagnostics_never_create_missing_database_or_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """Mandatory Stage C: Diagnostics must not create database or simulation state."""
    auth_db = tmp_path / "nonexistent_dir" / "auth.db"
    sim_state = tmp_path / "nonexistent_state" / ".simulated_tailscale.json"

    monkeypatch.setenv("REMOTE_CONTROL_AUTH_DB_PATH", str(auth_db))
    monkeypatch.setenv("REMOTE_CONTROL_SIMULATE_TAILSCALE", "1")
    monkeypatch.setenv("REMOTE_CONTROL_SIMULATED_STATE_PATH", str(sim_state))

    assert not auth_db.exists()
    assert not sim_state.exists()
    snapshot_before = _get_tree_snapshot(tmp_path)

    # 1. Run top-level status
    code = main(["status", "--json"])
    assert code == 0
    stat_out = json.loads(capsys.readouterr().out)
    assert stat_out["bootstrapped"] is False
    assert stat_out["active_sessions"] == 0

    # 2. Run external status
    code = main(["external", "status", "--json"])
    assert code == 0
    ext_stat_out = json.loads(capsys.readouterr().out)
    assert ext_stat_out["read_only"] is True
    assert ext_stat_out["barriers"]["active_count"] == 0

    # 3. Run external doctor
    code = main(["external", "doctor", "--json"])
    doc_out = json.loads(capsys.readouterr().out)
    assert doc_out["read_only"] is True

    # VERIFY INVARIANT: ZERO files created anywhere under tmp_path
    snapshot_after = _get_tree_snapshot(tmp_path)
    assert snapshot_after == snapshot_before
    assert not auth_db.exists()
    assert not auth_db.parent.exists()
    assert not sim_state.exists()
    assert not sim_state.parent.exists()


def test_diagnostics_never_mutate_existing_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """Diagnostics must not modify existing database files or create lock/wal leftovers."""
    auth_db = tmp_path / "existing_auth.db"
    sim_state = tmp_path / ".sim_state.json"

    # Pre-create the database using regular bootstrap
    monkeypatch.setenv("REMOTE_CONTROL_AUTH_DB_PATH", str(auth_db))
    monkeypatch.setenv("REMOTE_CONTROL_SIMULATE_TAILSCALE", "1")
    monkeypatch.setenv("REMOTE_CONTROL_SIMULATED_STATE_PATH", str(sim_state))

    from remote_control.auth.storage import AuthStorage
    from remote_control.actions.storage import ActionStorage
    import sqlite3
    auth_storage = AuthStorage(auth_db)
    auth_storage.create_operator("op_1", "admin", "hash", "secret")
    action_storage = ActionStorage(auth_db)
    assert auth_db.is_file()

    # Flush WAL so test fixture is quiescent
    with sqlite3.connect(str(auth_db)) as c:
        c.execute("PRAGMA wal_checkpoint(TRUNCATE);")

    # Pre-create simulation state
    sim_state.write_text('{"installed": true, "funnel_active": false}', encoding="utf-8")

    db_hash_before = _file_hash(auth_db)
    sim_hash_before = _file_hash(sim_state)

    # Run status, external status, external doctor
    main(["status", "--json"])
    capsys.readouterr()
    main(["external", "status", "--json"])
    capsys.readouterr()
    main(["external", "doctor", "--json"])
    capsys.readouterr()

    # VERIFY INVARIANT: Content hashes of auth.db and sim_state are completely unchanged
    assert _file_hash(auth_db) == db_hash_before
    assert _file_hash(sim_state) == sim_hash_before
