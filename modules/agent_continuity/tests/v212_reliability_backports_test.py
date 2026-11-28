"""Regression tests for v2.1.2 SQLite WAL concurrency and metadata-attachment contention backports."""

from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_continuity.dispatcher import DispatcherService
from agent_continuity.errors import ContinuityError
from agent_continuity.schema import SCHEMA_VERSION, ensure_schema, get_schema_version
from agent_continuity.service import ContinuityService


def test_concurrent_first_use_sqlite_wal_initialization(tmp_path: Path) -> None:
    db_path = tmp_path / "concurrent.sqlite"
    barrier = threading.Barrier(8)

    def _init_worker(_: int) -> int:
        # Use a short connect timeout so concurrent PRAGMA journal_mode=WAL / DDL contention is exercised.
        with closing(sqlite3.connect(str(db_path), timeout=0.05)) as conn:
            barrier.wait(timeout=5.0)
            ver = ensure_schema(conn)
            assert ver == SCHEMA_VERSION
            mode = conn.execute("PRAGMA journal_mode;").fetchone()
            assert mode is not None and str(mode[0]).casefold() == "wal"
            return int(get_schema_version(conn) or 0)

    with ThreadPoolExecutor(max_workers=8) as pool:
        versions = list(pool.map(_init_worker, range(8)))

    assert versions == [SCHEMA_VERSION] * 8


def test_attach_session_waits_for_metadata_contention_and_rejects_active_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    continuity = ContinuityService(tmp_path / "registry")
    dispatcher = DispatcherService(continuity)
    dispatcher.create_gui("BackportGUI", apply=True)
    slot = dispatcher.create_slot(gui="BackportGUI", name="Worker", apply=True)
    slot_id = slot["details"]["slot_id"]
    dispatcher.attach_session(gui="BackportGUI", name="Worker", provider="codex", session_id="sid-1", apply=True)

    # 1. Non-runtime metadata holder holds slot lock briefly -> attach_session waits and succeeds
    lock_held = threading.Event()

    def _metadata_holder() -> None:
        with dispatcher._hold_slot_lock(slot_id):  # noqa: SLF001
            lock_held.set()
            time.sleep(0.25)

    holder = threading.Thread(target=_metadata_holder)
    holder.start()
    assert lock_held.wait(timeout=2.0)

    monkeypatch.setattr(dispatcher, "observe_runtime_session", lambda *args, **kwargs: None)
    attached = dispatcher.attach_session(
        gui="BackportGUI", name="Worker", provider="codex", session_id="sid-2", apply=True
    )
    holder.join(timeout=5.0)
    assert attached["details"]["native_session_id"] == "sid-2"

    # 2. If an active provider session is observed while slot lock is held -> fail closed immediately
    lock_held2 = threading.Event()
    release_lock2 = threading.Event()

    def _active_holder() -> None:
        with dispatcher._hold_slot_lock(slot_id):  # noqa: SLF001
            lock_held2.set()
            release_lock2.wait(timeout=5.0)

    holder2 = threading.Thread(target=_active_holder)
    holder2.start()
    assert lock_held2.wait(timeout=2.0)
    try:
        monkeypatch.setattr(
            dispatcher,
            "observe_runtime_session",
            lambda *args, **kwargs: SimpleNamespace(status="in_use"),
        )
        with pytest.raises(ContinuityError, match="observed active provider session"):
            dispatcher.attach_session(
                gui="BackportGUI", name="Worker", provider="codex", session_id="sid-3", apply=True
            )
    finally:
        release_lock2.set()
        holder2.join(timeout=5.0)
