"""Regression tests for v2.1.3 SQLite WAL concurrency, real observation contract, and lock-order safety."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_continuity.dispatcher import DispatcherService, _mutation_lock
from agent_continuity.errors import ContinuityError
from agent_continuity.runtime_discovery import (
    AttachmentState,
    EvidenceAvailability,
    EvidenceConfidence,
    ManagementState,
    MatchStatus,
    ProcessLiveness,
    SessionIdentityState,
    SessionKey,
    SessionRuntimeObservation,
)
from agent_continuity.schema import SCHEMA_VERSION, ensure_schema, get_schema_version
from agent_continuity.service import ContinuityService


def _make_observation(
    *,
    liveness: ProcessLiveness = ProcessLiveness.EXITED,
    known_liveness: ProcessLiveness = ProcessLiveness.EXITED,
    match_status: MatchStatus = MatchStatus.NOT_OBSERVED,
    attachment: AttachmentState = AttachmentState.DETACHED,
    identity_conflict: bool = False,
    evidence_conflict: bool = False,
) -> SessionRuntimeObservation:
    return SessionRuntimeObservation(
        key=SessionKey(provider="codex", native_session_id="sid-1", environment_id="env-local"),
        captured_at=datetime.now(UTC),
        process_liveness=liveness,
        known_process_liveness=known_liveness,
        process_session_match=match_status,
        session_identity_state=SessionIdentityState.EXACT,
        interactive_attachment=attachment,
        attachment_confidence=EvidenceConfidence.EXACT,
        management=ManagementState.MANAGED,
        availability=EvidenceAvailability.COMPLETE,
        process_availability=EvidenceAvailability.COMPLETE,
        provider_store_availability=EvidenceAvailability.COMPLETE,
        managed_receipt_availability=EvidenceAvailability.COMPLETE,
        confidence=EvidenceConfidence.EXACT,
        provider_session_found=True,
        provider_activity_at=None,
        provider_last_turn_at=None,
        registry_association=True,
        processes=(),
        ancestry=(),
        managed_pane=None,
        historical_managed_panes=(),
        identity_conflict=identity_conflict,
        evidence_conflict=evidence_conflict,
        evidence=(),
    )


def test_concurrent_first_use_sqlite_wal_initialization(tmp_path: Path) -> None:
    db_path = tmp_path / "concurrent.sqlite"
    barrier = threading.Barrier(8)

    def _init_worker(_: int) -> int:
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


def test_attach_session_real_observation_contract_and_lock_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "registry"
    continuity = ContinuityService(home)
    dispatcher = DispatcherService(continuity)
    dispatcher.create_gui("BackportGUI", apply=True)
    slot = dispatcher.create_slot(gui="BackportGUI", name="Worker", apply=True)
    slot_id = slot["details"]["slot_id"]
    dispatcher.attach_session(gui="BackportGUI", name="Worker", provider="codex", session_id="sid-1", apply=True)

    # 1. Exited/detached observation + competing lock-order (slot lock -> _mutation_lock) has no AB-BA deadlock
    lock_held = threading.Event()

    def _slot_then_mutation() -> None:
        with dispatcher._hold_slot_lock(slot_id):  # noqa: SLF001
            lock_held.set()
            time.sleep(0.15)
            with _mutation_lock(home):
                pass

    holder = threading.Thread(target=_slot_then_mutation)
    holder.start()
    assert lock_held.wait(timeout=2.0)

    monkeypatch.setattr(
        dispatcher,
        "observe_runtime_session",
        lambda *args, **kwargs: _make_observation(
            liveness=ProcessLiveness.EXITED,
            known_liveness=ProcessLiveness.EXITED,
            match_status=MatchStatus.NOT_OBSERVED,
            attachment=AttachmentState.DETACHED,
        ),
    )
    attached = dispatcher.attach_session(
        gui="BackportGUI", name="Worker", provider="codex", session_id="sid-2", apply=True
    )
    holder.join(timeout=5.0)
    assert attached["details"]["native_session_id"] == "sid-2"

    # 2. Fail closed on running, ambiguous, attached, or conflicting SessionRuntimeObservation
    blocking_observations = [
        _make_observation(liveness=ProcessLiveness.RUNNING, match_status=MatchStatus.EXACT),
        _make_observation(liveness=ProcessLiveness.AMBIGUOUS),
        _make_observation(known_liveness=ProcessLiveness.RUNNING),
        _make_observation(match_status=MatchStatus.AMBIGUOUS),
        _make_observation(attachment=AttachmentState.ATTACHED),
        _make_observation(identity_conflict=True),
        _make_observation(evidence_conflict=True),
    ]
    lock_held2 = threading.Event()
    release_lock2 = threading.Event()

    def _hold_slot() -> None:
        with dispatcher._hold_slot_lock(slot_id):  # noqa: SLF001
            lock_held2.set()
            release_lock2.wait(timeout=5.0)

    holder2 = threading.Thread(target=_hold_slot)
    holder2.start()
    assert lock_held2.wait(timeout=2.0)
    try:
        for obs in blocking_observations:
            monkeypatch.setattr(dispatcher, "observe_runtime_session", lambda *args, _obs=obs, **kwargs: _obs)
            with pytest.raises(ContinuityError, match="observed runtime conflict"):
                dispatcher.attach_session(
                    gui="BackportGUI", name="Worker", provider="codex", session_id="sid-3", apply=True
                )
    finally:
        release_lock2.set()
        holder2.join(timeout=5.0)


def test_cross_process_slot_contention_bounded_wait_and_recovery(tmp_path: Path) -> None:
    home = tmp_path / "registry_xproc"
    continuity = ContinuityService(home)
    dispatcher = DispatcherService(continuity)
    dispatcher.create_gui("CrossProcGUI", apply=True)
    slot = dispatcher.create_slot(gui="CrossProcGUI", name="Worker", apply=True)
    slot_id = slot["details"]["slot_id"]

    # 1. Cross-process short metadata holder (0.25s) -> attach_session waits cleanly and succeeds
    short_proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import sys, time\n"
                "from pathlib import Path\n"
                "from agent_continuity.dispatcher import _slot_runtime_lock\n"
                "with _slot_runtime_lock(Path(sys.argv[1]), sys.argv[2], blocking=True):\n"
                "    print('LOCKED', flush=True)\n"
                "    time.sleep(0.25)\n"
            ),
            str(home),
            slot_id,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert short_proc.stdout is not None and short_proc.stdout.readline().strip() == "LOCKED"
        res = dispatcher.attach_session(
            gui="CrossProcGUI", name="Worker", provider="codex", session_id="sid-xproc-1", apply=True
        )
        assert res["details"]["native_session_id"] == "sid-xproc-1"
    finally:
        short_proc.wait(timeout=5.0)

    # 2. Long-held cross-process lock (>3s) -> attach_session fails closed within bounded ~1.5s wait
    long_proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import sys, time\n"
                "from pathlib import Path\n"
                "from agent_continuity.dispatcher import _slot_runtime_lock\n"
                "with _slot_runtime_lock(Path(sys.argv[1]), sys.argv[2], blocking=True):\n"
                "    print('LOCKED', flush=True)\n"
                "    time.sleep(4.0)\n"
            ),
            str(home),
            slot_id,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert long_proc.stdout is not None and long_proc.stdout.readline().strip() == "LOCKED"
        t0 = time.monotonic()
        with pytest.raises(ContinuityError, match="already has an active or launching session"):
            dispatcher.attach_session(
                gui="CrossProcGUI", name="Worker", provider="codex", session_id="sid-xproc-2", apply=True
            )
        assert (time.monotonic() - t0) < 3.0
    finally:
        long_proc.kill()
        long_proc.wait(timeout=2.0)


def test_concurrent_empty_registry_prepare_start_and_equal_timestamp_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_continuity.events import append_event
    from agent_continuity.materializer import SQLiteMaterializer
    from agent_continuity.models import EventEnvelope, EventType

    # 1. Concurrent empty-registry prepare_start reserves exactly one pending launch
    home = tmp_path / "empty_reg"
    barrier = threading.Barrier(4)

    def _run_prepare(idx: int) -> str:
        svc = ContinuityService(home)
        disp = DispatcherService(svc)
        barrier.wait(timeout=5.0)
        try:
            disp.prepare_start(gui="RaceGUI", name="AgentOne", provider="codex", apply=True)
            return "reserved"
        except ContinuityError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(_run_prepare, range(4)))

    assert outcomes.count("reserved") == 1
    assert all(code == "reserved" or code == "invalid_input" for code in outcomes)
    disp_ro = DispatcherService(ContinuityService(home))
    assert len(disp_ro.list_pending_launches()) == 1

    # 2. Equal-timestamp dependencies with adversarial event_ids + interrupted .tmp. publication
    home2 = tmp_path / "equal_ts_reg"
    ts = "2026-11-27T12:00:00.000000Z"
    env_id = "env_eq_1"
    gui_id = "gui_eq_1"
    slot_id = "slot_eq_1"
    events = [
        EventEnvelope(
            event_id="evt_zzz_env",
            event_schema_version=1,
            event_type=EventType.ENVIRONMENT_REGISTERED.value,
            provider=None,
            environment_id=env_id,
            native_session_id=None,
            source_timestamp=ts,
            observed_timestamp=ts,
            source_adapter_version="2.1.3",
            payload={"environment_id": env_id, "runtime_kind": "windows", "label": "Win"},
        ),
        EventEnvelope(
            event_id="evt_yyy_gui",
            event_schema_version=1,
            event_type=EventType.DISPATCHER_GUI_REGISTERED.value,
            provider=None,
            environment_id=env_id,
            native_session_id=None,
            source_timestamp=ts,
            observed_timestamp=ts,
            source_adapter_version="2.1.3",
            payload={"gui_id": gui_id, "alias": "EqGUI", "alias_key": "eqgui"},
        ),
        EventEnvelope(
            event_id="evt_xxx_slot",
            event_schema_version=1,
            event_type=EventType.DISPATCHER_SLOT_CREATED.value,
            provider=None,
            environment_id=env_id,
            native_session_id=None,
            source_timestamp=ts,
            observed_timestamp=ts,
            source_adapter_version="2.1.3",
            payload={"slot_id": slot_id, "gui_id": gui_id, "name": "Alpha", "name_key": "alpha"},
        ),
        EventEnvelope(
            event_id="evt_aaa_launch",
            event_schema_version=1,
            event_type=EventType.DISPATCHER_LAUNCH_REQUESTED.value,
            provider="codex",
            environment_id=env_id,
            native_session_id=None,
            source_timestamp=ts,
            observed_timestamp=ts,
            source_adapter_version="2.1.3",
            payload={"launch_id": "launch_eq_1", "slot_id": slot_id, "cwd": str(tmp_path)},
        ),
    ]
    for ev in events:
        append_event(home2, ev)
    # Interrupted temporary spool file must be ignored cleanly during sync and rebuild
    (home2 / "events" / env_id / ".tmp.9999.partial.json").write_text("{truncated", encoding="utf-8")

    mat = SQLiteMaterializer(home2)
    synced = mat.sync_from_spools()
    assert synced.issues == []
    assert synced.ingested_count == 4
    rebuilt = mat.rebuild_from_spools()
    assert rebuilt.rebuilt is True
    assert rebuilt.issues == []
    assert rebuilt.ingested_count == 4

    # 3. Unknown liveness falls back to bounded lock acquisition (succeeds on short contention, not claimed inactive)
    disp2 = DispatcherService(ContinuityService(home2))
    lock_held = threading.Event()

    def _short_meta() -> None:
        with disp2._hold_slot_lock(slot_id):  # noqa: SLF001
            lock_held.set()
            time.sleep(0.15)

    t = threading.Thread(target=_short_meta)
    t.start()
    assert lock_held.wait(timeout=2.0)
    monkeypatch.setattr(
        disp2,
        "observe_runtime_session",
        lambda *args, **kwargs: _make_observation(
            liveness=ProcessLiveness.UNKNOWN,
            known_liveness=ProcessLiveness.UNKNOWN,
            match_status=MatchStatus.NOT_OBSERVED,
            attachment=AttachmentState.UNKNOWN,
        ),
    )
    # Pending launch blocks attach after acquiring slot lock cleanly (did not fail on UNKNOWN observation)
    with pytest.raises(ContinuityError, match="unresolved pending launch"):
        disp2.attach_session(gui="EqGUI", name="Alpha", provider="codex", session_id="sid-eq", apply=True)
    t.join(timeout=5.0)
