from __future__ import annotations

import os
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest
from terminal_launcher.managed import (
    InterruptionState,
    LaunchSubmissionState,
    ManagedPaneReservation,
    ManagedProcessState,
    ManagedProcessStore,
    ProcessLiveness,
)


def reservation(pane_id: str, pane_index: int = 0) -> ManagedPaneReservation:
    return ManagedPaneReservation(pane_id, tab_index=0, pane_index=pane_index, requested_layout="single")


def relay_identity() -> tuple[int, int]:
    pid = os.getpid()
    return pid, pid * 10


def reserve_started(store: ManagedProcessStore, pane_id: str = "launch:0:0") -> str:
    store.reserve_launch("launch", "window", (reservation(pane_id),))
    store.mark_submission_started("launch")
    relay_pid, relay_created = relay_identity()
    token = store.claim_pane("launch", pane_id, relay_pid=relay_pid, relay_process_created=relay_created)
    assert token is not None
    store.record_started(
        "launch",
        pane_id,
        claim_token=token,
        pid=800,
        process_created=8000,
        relay_pid=relay_pid,
        relay_process_created=relay_created,
    )
    return token


def test_complete_launch_reservation_rolls_back_on_partial_insert_error(tmp_path):
    store = ManagedProcessStore(tmp_path / "atomic.sqlite3")
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            """CREATE TRIGGER reject_second_pane BEFORE INSERT ON managed_panes
               WHEN NEW.requested_pane_index = 1 BEGIN SELECT RAISE(ABORT, 'test fault'); END"""
        )

    with pytest.raises(sqlite3.IntegrityError, match="test fault"):
        store.reserve_launch("launch", "window", (reservation("launch:0:0"), reservation("launch:0:1", 1)))

    assert store.enumerate_processes() == ()
    assert store.get_submission_state("launch") is None


def test_legacy_store_migration_keeps_ambiguous_panes_non_claimable(tmp_path):
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TABLE managed_panes (
                launch_id TEXT NOT NULL, pane_id TEXT PRIMARY KEY, window_id_hash TEXT NOT NULL,
                requested_tab_index INTEGER NOT NULL, requested_pane_index INTEGER NOT NULL,
                requested_layout TEXT NOT NULL, submitted_at REAL NOT NULL, state TEXT NOT NULL,
                pid INTEGER, process_created INTEGER, relay_pid INTEGER, relay_process_created INTEGER,
                started_at REAL, exited_at REAL, exit_code INTEGER, failure_code TEXT,
                shutdown_requested INTEGER NOT NULL DEFAULT 0, shutdown_delivered INTEGER NOT NULL DEFAULT 0
            )"""
        )
        connection.execute(
            """INSERT INTO managed_panes
               (launch_id, pane_id, window_id_hash, requested_tab_index, requested_pane_index,
                requested_layout, submitted_at, state, shutdown_requested)
               VALUES ('legacy', 'legacy:0:0', 'hash', 0, 0, 'single', 1.0, 'unknown', 1)"""
        )

    store = ManagedProcessStore(database)
    [record] = store.enumerate_processes()

    assert record.state is ManagedProcessState.UNKNOWN
    assert record.submission_state is LaunchSubmissionState.AMBIGUOUS
    assert record.interruption_state is InterruptionState.UNKNOWN
    relay_pid, relay_created = relay_identity()
    assert store.claim_pane("legacy", "legacy:0:0", relay_pid=relay_pid, relay_process_created=relay_created) is None


def test_duplicate_and_concurrent_relays_can_claim_a_pane_only_once(tmp_path):
    store = ManagedProcessStore(
        tmp_path / "claim.sqlite3",
        process_identity_lookup=lambda pid: (pid, pid * 10),
        process_liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
    )
    store.reserve_launch("launch", "window", (reservation("launch:0:0"),))
    store.mark_submission_started("launch")

    with ThreadPoolExecutor(max_workers=12) as executor:
        claims = list(
            executor.map(
                lambda _: store.claim_pane(
                    "launch", "launch:0:0", relay_pid=relay_identity()[0],
                    relay_process_created=relay_identity()[1],
                ),
                range(12),
            )
        )

    assert sum(token is not None for token in claims) == 1
    [record] = store.enumerate_processes()
    assert record.state is ManagedProcessState.CLAIMED
    assert record.relay_pid == relay_identity()[0]


def test_definite_rejection_marks_only_unclaimed_panes_and_late_receipt_is_preserved(tmp_path):
    store = ManagedProcessStore(
        tmp_path / "rejection.sqlite3",
        process_identity_lookup=lambda pid: (pid, pid * 10),
        process_liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
    )
    store.reserve_launch("launch", "window", (reservation("launch:0:0"), reservation("launch:0:1", 1)))
    store.mark_submission_started("launch")
    relay_pid, relay_created = relay_identity()
    token = store.claim_pane("launch", "launch:0:0", relay_pid=relay_pid, relay_process_created=relay_created)
    assert token is not None

    store.mark_submission_outcome("launch", LaunchSubmissionState.REJECTED, failure_code="terminal_rejected")
    store.record_started(
        "launch", "launch:0:0", claim_token=token, pid=800, process_created=8000,
        relay_pid=relay_pid, relay_process_created=relay_created,
    )
    records = {record.pane_id: record for record in store.enumerate_processes()}

    assert records["launch:0:0"].spawn_acknowledged
    assert records["launch:0:0"].state is ManagedProcessState.RUNNING
    assert records["launch:0:1"].state is ManagedProcessState.FAILED
    assert records["launch:0:0"].submission_state is LaunchSubmissionState.REJECTED


def test_ambiguous_submission_preserves_reserved_pane_for_one_late_original_relay(tmp_path):
    store = ManagedProcessStore(
        tmp_path / "ambiguous.sqlite3",
        process_identity_lookup=lambda pid: (pid, pid * 10),
        process_liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
    )
    store.reserve_launch("launch", "window", (reservation("launch:0:0"),))
    store.mark_submission_started("launch")
    store.mark_submission_outcome("launch", LaunchSubmissionState.AMBIGUOUS)

    relay_pid, relay_created = relay_identity()
    first = store.claim_pane("launch", "launch:0:0", relay_pid=relay_pid, relay_process_created=relay_created)
    duplicate = store.claim_pane("launch", "launch:0:0", relay_pid=relay_pid, relay_process_created=relay_created)

    assert first is not None
    assert duplicate is None
    [record] = store.enumerate_processes()
    assert record.submission_state is LaunchSubmissionState.AMBIGUOUS
    assert record.state is ManagedProcessState.CLAIMED


def test_interruption_between_claim_and_spawn_is_recoverable_but_never_retried(tmp_path):
    relay_pid, relay_created = relay_identity()
    liveness = {relay_pid: ProcessLiveness.ALIVE}
    store = ManagedProcessStore(
        tmp_path / "interrupted.sqlite3",
        process_identity_lookup=lambda pid: (pid, pid * 10),
        process_liveness_lookup=lambda pid: liveness.get(pid, ProcessLiveness.UNKNOWN),
    )
    store.reserve_launch("launch", "window", (reservation("launch:0:0"),))
    store.mark_submission_started("launch")
    token = store.claim_pane("launch", "launch:0:0", relay_pid=relay_pid, relay_process_created=relay_created)
    assert token is not None
    liveness[relay_pid] = ProcessLiveness.EXITED

    recovered = store.enumerate_processes()[0]
    retry = store.claim_pane("launch", "launch:0:0", relay_pid=relay_pid, relay_process_created=relay_created)

    assert recovered.state is ManagedProcessState.UNKNOWN
    assert recovered.owner_liveness is ProcessLiveness.EXITED
    assert retry is None


def test_process_creation_identity_and_liveness_are_reported_separately(tmp_path):
    store = ManagedProcessStore(
        tmp_path / "liveness.sqlite3",
        process_identity_lookup=lambda pid: (pid, pid * 10),
        process_liveness_lookup=lambda pid: (
            ProcessLiveness.ALIVE if pid == os.getpid() else ProcessLiveness.EXITED
        ),
    )
    reserve_started(store)

    [record] = store.enumerate_processes()

    assert record.process_created == 8000
    assert record.state is ManagedProcessState.UNKNOWN
    assert record.liveness is ProcessLiveness.EXITED
    assert record.exit_code is None


def test_missing_creation_time_is_unknown_even_when_pid_is_live(tmp_path):
    store = ManagedProcessStore(
        tmp_path / "missing-creation.sqlite3",
        process_identity_lookup=lambda pid: (pid, pid * 10),
        process_liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
    )
    store.reserve_launch("launch", "window", (reservation("launch:0:0"),))
    store.mark_submission_started("launch")
    relay_pid, relay_created = relay_identity()
    token = store.claim_pane("launch", "launch:0:0", relay_pid=relay_pid, relay_process_created=relay_created)
    assert token is not None
    store.record_started(
        "launch", "launch:0:0", claim_token=token, pid=800, process_created=None,
        relay_pid=relay_pid, relay_process_created=relay_created,
    )

    [record] = store.enumerate_processes()

    assert record.spawn_acknowledged
    assert record.state is ManagedProcessState.UNKNOWN
    assert record.liveness is ProcessLiveness.ALIVE


def test_start_and_exit_receipts_are_conditional_and_idempotency_is_rejected(tmp_path):
    store = ManagedProcessStore(
        tmp_path / "conditional-receipts.sqlite3",
        process_identity_lookup=lambda pid: (pid, pid * 10),
        process_liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
    )
    token = reserve_started(store)
    with pytest.raises(ValueError, match="stale or does not belong"):
        store.record_started(
            "launch", "launch:0:0", claim_token=token, pid=800, process_created=8000,
            relay_pid=relay_identity()[0], relay_process_created=relay_identity()[1],
        )

    store.record_exit("launch", "launch:0:0", claim_token=token, exit_code=0)
    with pytest.raises(ValueError, match="no matching start receipt"):
        store.record_exit("launch", "launch:0:0", claim_token=token, exit_code=1)
    [record] = store.enumerate_processes()
    assert record.state is ManagedProcessState.EXITED
    assert record.exit_code == 0


def test_shutdown_delivery_is_at_most_once_under_concurrency(tmp_path):
    store = ManagedProcessStore(
        tmp_path / "shutdown-race.sqlite3",
        process_identity_lookup=lambda pid: (pid, pid * 10),
        process_liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
    )
    relay_pid, relay_created = relay_identity()
    reserve_started(store)
    assert store.request_interrupt("launch:0:0").accepted
    signals: list[int] = []

    def deliver(_):
        return store.deliver_interruption(
            "launch:0:0",
            relay_pid=relay_pid,
            relay_process_created=relay_created,
            signal_process_group=lambda pid: signals.append(pid) or True,
        )

    with ThreadPoolExecutor(max_workers=12) as executor:
        outcomes = list(executor.map(deliver, range(12)))

    assert sum(outcomes) == 1
    assert signals == [800]
    assert store.get_interruption_state("launch:0:0") is InterruptionState.DELIVERED


def test_interrupted_delivery_is_ambiguous_and_never_signaled_twice(tmp_path):
    store = ManagedProcessStore(
        tmp_path / "interrupted-delivery.sqlite3",
        process_identity_lookup=lambda pid: (pid, pid * 10),
        process_liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
    )
    relay_pid, relay_created = relay_identity()
    reserve_started(store)
    store.request_interrupt("launch:0:0")
    signals: list[int] = []

    def signal_then_interrupt(pid):
        signals.append(pid)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        store.deliver_interruption(
            "launch:0:0", relay_pid=relay_pid, relay_process_created=relay_created,
            signal_process_group=signal_then_interrupt
        )

    assert not store.deliver_interruption(
        "launch:0:0", relay_pid=relay_pid, relay_process_created=relay_created,
        signal_process_group=lambda pid: signals.append(pid) or True,
    )
    assert signals == [800]
    assert store.get_interruption_state("launch:0:0") is InterruptionState.DELIVERING


def test_wrong_relay_identity_cannot_deliver_an_interruption(tmp_path):
    relay_pid, relay_created = relay_identity()
    store = ManagedProcessStore(
        tmp_path / "relay-owner.sqlite3",
        process_identity_lookup=lambda pid: (pid, pid * 10),
        process_liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
    )
    reserve_started(store)
    store.request_interrupt("launch:0:0")
    signals: list[int] = []

    delivered = store.deliver_interruption(
        "launch:0:0", relay_pid=relay_pid + 1, relay_process_created=(relay_pid + 1) * 10,
        signal_process_group=lambda pid: signals.append(pid) or True,
    )

    assert not delivered
    assert signals == []
    assert store.get_interruption_state("launch:0:0") is InterruptionState.PENDING


def test_correct_stored_relay_identity_cannot_be_spoofed_by_another_caller(tmp_path, monkeypatch):
    import terminal_launcher.managed as managed_module

    store = ManagedProcessStore(
        tmp_path / "spoofed-caller.sqlite3",
        process_identity_lookup=lambda pid: (pid, pid * 10),
        process_liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
    )
    relay_pid, relay_created = relay_identity()
    reserve_started(store)
    assert store.request_interrupt("launch:0:0").accepted
    signals = []

    with monkeypatch.context() as patcher:
        patcher.setattr(managed_module.os, "getpid", lambda: 701)
        delivered = store.deliver_interruption(
            "launch:0:0",
            relay_pid=relay_pid,
            relay_process_created=relay_created,
            signal_process_group=lambda pid: signals.append(pid) or True,
        )
        compatibility_delivered = store.deliver_shutdown_request(
            "launch:0:0", signal_process_group=lambda pid: signals.append(pid) or True
        )

    assert not delivered
    assert not compatibility_delivered
    assert signals == []
    assert store.get_interruption_state("launch:0:0") is InterruptionState.PENDING


def test_claim_and_receipt_compatibility_methods_require_actual_owner(tmp_path, monkeypatch):
    import terminal_launcher.managed as managed_module

    relay_pid, relay_created = relay_identity()
    store = ManagedProcessStore(
        tmp_path / "owner-receipts.sqlite3",
        process_identity_lookup=lambda pid: (pid, pid * 10),
        process_liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
    )
    store.reserve_launch("launch", "window", (reservation("launch:0:0"),))
    store.mark_submission_started("launch")
    with pytest.raises(ValueError, match="claimed by its relay"):
        store.record_failure("launch:0:0", failure_code="unowned_failure")

    token = store.claim_pane(
        "launch", "launch:0:0", relay_pid=relay_pid, relay_process_created=relay_created
    )
    assert token is not None
    assert store.claim_pane(
        "launch", "launch:0:0", relay_pid=relay_pid + 1, relay_process_created=(relay_pid + 1) * 10
    ) is None

    with monkeypatch.context() as patcher:
        patcher.setattr(managed_module.os, "getpid", lambda: relay_pid + 1)
        with pytest.raises(ValueError, match="owning relay process"):
            store.record_started(
                "launch", "launch:0:0", claim_token=token, pid=800, process_created=8000,
                relay_pid=relay_pid, relay_process_created=relay_created,
            )
        with pytest.raises(ValueError, match="owning relay process"):
            store.record_spawn_failure(
                "launch", "launch:0:0", claim_token=token, failure_code="spawn_failed"
            )

    store.record_started(
        "launch", "launch:0:0", claim_token=token, pid=800, process_created=8000,
        relay_pid=relay_pid, relay_process_created=relay_created,
    )
    with monkeypatch.context() as patcher:
        patcher.setattr(managed_module.os, "getpid", lambda: relay_pid + 1)
        with pytest.raises(ValueError, match="owning relay process"):
            store.record_exit("launch", "launch:0:0", claim_token=token, exit_code=0)
        with pytest.raises(ValueError, match="owning relay process"):
            store.finish_interruption_delivery(
                "launch:0:0", relay_pid=relay_pid, relay_process_created=relay_created,
                outcome=InterruptionState.DELIVERED,
            )

    [record] = store.enumerate_processes()
    assert record.state is ManagedProcessState.RUNNING
    assert record.exit_code is None


def _relay_store(tmp_path, name="relay.sqlite3"):
    store = ManagedProcessStore(
        tmp_path / name,
        process_identity_lookup=lambda pid: (pid, pid * 10),
        process_liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
    )
    store.reserve_launch("launch", "window", (reservation("launch:0:0"),))
    store.mark_submission_started("launch")
    return store


def _managed_payload(store):
    return {"store_path": str(store.path), "launch_id": "launch", "pane_id": "launch:0:0"}


def test_duplicate_relay_payload_does_not_spawn_a_second_child(tmp_path):
    from terminal_launcher.backends._pane_runner import run_managed_payload

    store = _relay_store(tmp_path)
    spawns = []

    class Child:
        pid = 800

        def wait(self, timeout=None):
            return 0

    def popen(*_args, **_kwargs):
        spawns.append(1)
        return Child()

    for _ in range(2):
        assert run_managed_payload(
            ["pwsh.exe", "-NoLogo", "-Command", "exit 0"],
            None,
            _managed_payload(store),
            popen=popen,
            identity_lookup=lambda pid: (pid, pid * 10),
            liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
            store_factory=lambda *_args, **_kwargs: store,
        ) == 0

    assert spawns == [1]
    [record] = store.enumerate_processes()
    assert record.state is ManagedProcessState.EXITED
    assert record.pid == 800


def test_rejected_launch_does_not_allow_a_delayed_relay_to_spawn(tmp_path):
    from terminal_launcher.backends._pane_runner import run_managed_payload

    store = _relay_store(tmp_path)
    store.mark_submission_outcome("launch", LaunchSubmissionState.REJECTED)
    spawns = []

    def popen(*_args, **_kwargs):
        spawns.append(1)
        raise AssertionError("rejected request must not spawn")

    assert run_managed_payload(
        ["pwsh.exe"], None, _managed_payload(store), popen=popen,
        identity_lookup=lambda pid: (pid, pid * 10),
        liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
        store_factory=lambda *_args, **_kwargs: store,
    ) == 0
    assert spawns == []
    assert store.enumerate_processes()[0].state is ManagedProcessState.FAILED


def test_interrupted_after_claim_before_spawn_is_not_retried(tmp_path):
    from terminal_launcher.backends._pane_runner import run_managed_payload

    store = _relay_store(tmp_path)
    spawns = []

    def interrupted_spawn(*_args, **_kwargs):
        spawns.append(1)
        raise KeyboardInterrupt

    kwargs = dict(
        identity_lookup=lambda pid: (pid, pid * 10),
        liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
        store_factory=lambda *_args, **_kwargs: store,
    )
    with pytest.raises(KeyboardInterrupt):
        run_managed_payload(["pwsh.exe"], None, _managed_payload(store), popen=interrupted_spawn, **kwargs)

    assert run_managed_payload(["pwsh.exe"], None, _managed_payload(store), popen=interrupted_spawn, **kwargs) == 0
    assert spawns == [1]
    assert store.enumerate_processes()[0].state is ManagedProcessState.CLAIMED


def test_relay_uses_adaptive_pane_scoped_queries(tmp_path):
    from terminal_launcher.backends._pane_runner import run_managed_payload

    store = _relay_store(tmp_path)
    wait_timeouts = []
    queried_panes = []
    child = type("Child", (), {"pid": 800})()

    def wait(timeout=None):
        wait_timeouts.append(timeout)
        if len(wait_timeouts) < 4:
            raise subprocess.TimeoutExpired("pwsh.exe", timeout)
        return 0

    child.wait = wait
    original_query = store.get_interruption_state

    def query(pane_id):
        queried_panes.append(pane_id)
        return original_query(pane_id)

    store.get_interruption_state = query
    assert run_managed_payload(
        ["pwsh.exe"], None, _managed_payload(store), popen=lambda *_a, **_k: child,
        identity_lookup=lambda pid: (pid, pid * 10),
        liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
        store_factory=lambda *_args, **_kwargs: store,
        poll_interval=0.05,
        max_poll_interval=0.4,
    ) == 0

    assert wait_timeouts == [0.05, 0.1, 0.2, 0.4]
    assert queried_panes == ["launch:0:0"] * 3


def test_transient_start_receipt_failure_retries_until_child_is_tracked(tmp_path):
    from terminal_launcher.backends._pane_runner import run_managed_payload

    store = _relay_store(tmp_path)
    child = type("Child", (), {"pid": 800, "wait": lambda self, timeout=None: 0})()
    original_record_started = store.record_started
    attempts = []

    def fail_start(*args, **kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise sqlite3.OperationalError("temporary receipt fault")
        return original_record_started(*args, **kwargs)

    store.record_started = fail_start
    assert run_managed_payload(
        ["pwsh.exe"], None, _managed_payload(store), popen=lambda *_a, **_k: child,
        identity_lookup=lambda pid: (pid, pid * 10),
        liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
        store_factory=lambda *_args, **_kwargs: store,
    ) == 0

    assert len(attempts) >= 3
    [record] = store.enumerate_processes()
    assert record.state is ManagedProcessState.EXITED
    assert record.spawn_acknowledged


def test_permanent_receipt_failure_is_reported_without_abandoning_child(tmp_path, capsys):
    from terminal_launcher.backends._pane_runner import run_managed_payload

    store = _relay_store(tmp_path)
    waits = []

    class Child:
        pid = 800

        def wait(self, timeout=None):
            waits.append(timeout)
            if len(waits) == 1:
                raise subprocess.TimeoutExpired("pwsh.exe", timeout)
            return 0

    def unavailable_receipt(*_args, **_kwargs):
        raise sqlite3.OperationalError("test database fault")

    store.record_started = unavailable_receipt
    assert run_managed_payload(
        ["pwsh.exe"], None, _managed_payload(store), popen=lambda *_a, **_k: Child(),
        identity_lookup=lambda pid: (pid, pid * 10),
        liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
        store_factory=lambda *_args, **_kwargs: store,
    ) == 0

    assert len(waits) == 2
    assert "without durable start or exit receipts" in capsys.readouterr().err
    [record] = store.enumerate_processes()
    assert record.state is ManagedProcessState.CLAIMED
    assert not record.spawn_acknowledged
