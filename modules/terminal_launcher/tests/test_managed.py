from __future__ import annotations

import base64
import json
import os
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from terminal_launcher.backends.windows_terminal import WindowsTerminalBackend
from terminal_launcher.managed import ManagedProcessState, ManagedProcessStore, ProcessLiveness
from terminal_launcher.models import PaneSpec, TabSpec, TerminalLaunchPlan


def test_managed_store_connection_context_closes_connection(tmp_path):
    store = ManagedProcessStore(tmp_path / "managed.sqlite3")

    with store._connect() as connection:
        connection.execute("SELECT 1").fetchone()

    try:
        connection.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        return
    raise AssertionError("managed store connection remained open after its context")


def test_managed_receipts_are_durable_minimal_and_validate_process_creation_time(tmp_path):
    database = tmp_path / "managed.sqlite3"
    store = ManagedProcessStore(
        database,
        process_identity_lookup=lambda pid: (pid, 123456),
        process_liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
    )
    store.register_submission(
        launch_id="launch-1",
        pane_id="launch-1:0:0",
        window_id="private-window-name",
        tab_index=0,
        pane_index=0,
        requested_layout="single",
    )

    store.record_started("launch-1:0:0", pid=321, process_created=123456)

    [record] = store.enumerate_processes()
    assert record.state is ManagedProcessState.RUNNING
    assert record.pid == 321
    assert record.process_created == 123456
    assert len(record.window_id_hash) == 64
    assert record.readiness == "unknown"
    assert record.requested_layout == "single"
    stored = database.read_bytes()
    assert b"private-window-name" not in stored
    assert b"password" not in stored


def test_managed_store_resolves_relative_path_before_relay_launch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    store = ManagedProcessStore(Path("runtime") / "managed.sqlite3")

    assert store.path == tmp_path / "runtime" / "managed.sqlite3"
    assert store.path.is_absolute()


def test_legacy_keyword_receipt_and_failure_methods_remain_available(tmp_path):
    store = ManagedProcessStore(
        tmp_path / "legacy-api.sqlite3",
        process_identity_lookup=lambda pid: (pid, 123),
        process_liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
    )
    store.register_submission(
        launch_id="legacy", pane_id="legacy:0:0", window_id="window", tab_index=0,
        pane_index=0, requested_layout="single",
    )
    relay_pid = os.getpid()
    claim = store.claim_pane("legacy", "legacy:0:0", relay_pid=relay_pid, relay_process_created=123)
    assert claim is not None
    store.record_failure(pane_id="legacy:0:0", failure_code="child_spawn_failed")
    store.register_submission(
        launch_id="legacy", pane_id="legacy:0:1", window_id="window", tab_index=0,
        pane_index=1, requested_layout="two-column",
    )
    store.record_started(pane_id="legacy:0:1", pid=321, process_created=123)
    store.record_exit(pane_id="legacy:0:1", exit_code=0)

    records = {record.pane_id: record for record in store.enumerate_processes()}
    assert records["legacy:0:0"].state is ManagedProcessState.FAILED
    assert records["legacy:0:1"].state is ManagedProcessState.EXITED


def test_stale_pid_is_never_signaled(tmp_path):
    store = ManagedProcessStore(
        tmp_path / "managed.sqlite3",
        process_identity_lookup=lambda pid: (pid, 999),
        process_liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
    )
    store.register_submission(
        launch_id="launch-2",
        pane_id="launch-2:0:0",
        window_id="window",
        tab_index=0,
        pane_index=0,
        requested_layout="single",
    )
    store.record_started("launch-2:0:0", pid=123, process_created=456)

    result = store.request_graceful_shutdown("launch-2:0:0")

    assert not result.accepted
    assert result.reason == "stale_process_identity"


def test_graceful_shutdown_is_requested_for_exact_owned_process_only(tmp_path):
    store = ManagedProcessStore(
        tmp_path / "managed.sqlite3",
        process_identity_lookup=lambda pid: (pid, 456),
        process_liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
    )
    store.register_submission(
        launch_id="launch-3",
        pane_id="launch-3:0:1",
        window_id="window",
        tab_index=0,
        pane_index=1,
        requested_layout="two-column",
    )
    store.record_started(
        "launch-3:0:1", pid=234, process_created=456, relay_pid=os.getpid(), relay_process_created=456
    )

    result = store.request_graceful_shutdown("launch-3:0:1")

    assert result.accepted
    [record] = store.enumerate_processes()
    assert record.state is ManagedProcessState.RUNNING
    assert record.shutdown_requested


def test_relay_consumes_shutdown_request_with_owned_process_group(tmp_path):
    store = ManagedProcessStore(
        tmp_path / "managed.sqlite3",
        process_identity_lookup=lambda pid: (pid, 456),
        process_liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
    )
    store.register_submission(
        launch_id="launch-3b",
        pane_id="launch-3b:0:0",
        window_id="window",
        tab_index=0,
        pane_index=0,
        requested_layout="single",
    )
    store.record_started(
        "launch-3b:0:0", pid=345, process_created=456, relay_pid=os.getpid(), relay_process_created=456
    )
    store.request_graceful_shutdown("launch-3b:0:0")
    signals = []

    [request] = store.pending_shutdown_requests()
    assert store.deliver_shutdown_request(request.pane_id, signal_process_group=lambda pid: signals.append(pid) or True)
    assert signals == [345]
    assert store.pending_shutdown_requests() == ()


def test_exit_receipt_and_interrupted_submission_are_distinct(tmp_path):
    store = ManagedProcessStore(
        tmp_path / "managed.sqlite3",
        process_identity_lookup=lambda pid: (pid, 200),
        process_liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
    )
    store.register_submission(
        launch_id="launch-4",
        pane_id="launch-4:0:0",
        window_id="window",
        tab_index=0,
        pane_index=0,
        requested_layout="single",
    )
    store.register_submission(
        launch_id="launch-4",
        pane_id="launch-4:0:1",
        window_id="window",
        tab_index=0,
        pane_index=1,
        requested_layout="two-column",
    )
    store.record_started("launch-4:0:0", pid=100, process_created=200)
    store.record_exit("launch-4:0:0", exit_code=7)

    records = {record.pane_id: record for record in store.enumerate_processes()}

    assert records["launch-4:0:0"].state is ManagedProcessState.EXITED
    assert records["launch-4:0:0"].exit_code == 7
    assert records["launch-4:0:1"].state is ManagedProcessState.RESERVED


def test_concurrent_receipts_remain_queryable(tmp_path):
    store = ManagedProcessStore(
        tmp_path / "managed.sqlite3",
        process_identity_lookup=lambda pid: (pid, pid + 1),
        process_liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
    )

    def record(index):
        pane_id = f"launch-5:{index}"
        store.register_submission(
            launch_id="launch-5",
            pane_id=pane_id,
            window_id="window",
            tab_index=index,
            pane_index=0,
            requested_layout="single",
        )
        store.record_started(pane_id, pid=1000 + index, process_created=1001 + index)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(record, range(32)))

    assert len(store.enumerate_processes()) == 32


def test_managed_launch_reports_submission_separately_from_spawn_and_keeps_args_out_of_store(tmp_path, monkeypatch):
    database = tmp_path / "managed.sqlite3"
    store = ManagedProcessStore(database, process_identity_lookup=lambda pid: (pid, 444))

    class LaunchAndAcknowledge:
        def __call__(self, command, **kwargs):
            encoded = command[-1]
            payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            managed = payload["managed"]
            assert payload["argv"] == ["pwsh.exe", "-NoLogo", "-NoExit", "-Command", "Write-Output secret"]
            assert managed["pane_id"] == "launch-6:0:0"
            store.record_started(managed["pane_id"], pid=987, process_created=444)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("terminal_launcher.backends.windows_terminal.sys.platform", "win32")
    plan = TerminalLaunchPlan(
        (TabSpec("PowerShell", (PaneSpec("PowerShell", ("pwsh.exe", "-NoLogo", "-NoExit", "-Command", "Write-Output secret")),)),),
        target_window="scripts-work",
    )
    backend = WindowsTerminalBackend(executable="wt.exe", runner=LaunchAndAcknowledge())

    result = backend.launch_managed(plan, launch_id="launch-6", store=store)

    assert result.submission.status.value == "submitted"
    assert result.panes[0].spawn_acknowledged
    assert result.panes[0].readiness == "unknown"
    assert b"Write-Output secret" not in database.read_bytes()


def test_managed_launch_requires_named_window_target(tmp_path):
    store = ManagedProcessStore(tmp_path / "managed.sqlite3")
    plan = TerminalLaunchPlan((TabSpec("PowerShell", (PaneSpec("PowerShell", ("pwsh.exe",)),)),))
    backend = WindowsTerminalBackend(executable="wt.exe")

    result = backend.launch_managed(plan, launch_id="launch-7", store=store)

    assert result.submission.status.value == "failed"
    assert "target_window" in result.submission.diagnostic


def test_partial_managed_launch_reports_acknowledged_and_unacknowledged_panes_separately(tmp_path, monkeypatch):
    database = tmp_path / "partial.sqlite3"
    store = ManagedProcessStore(
        database,
        process_identity_lookup=lambda pid: (pid, 111),
        process_liveness_lookup=lambda _pid: ProcessLiveness.ALIVE,
    )

    class PartialLaunch:
        def __call__(self, command, **kwargs):
            for encoded in command:
                try:
                    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
                except (ValueError, json.JSONDecodeError):
                    continue
                if isinstance(payload, dict) and payload.get("managed", {}).get("pane_id") == "launch-8:0:0":
                    store.record_started("launch-8:0:0", pid=888, process_created=111)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("terminal_launcher.backends.windows_terminal.sys.platform", "win32")
    plan = TerminalLaunchPlan(
        (TabSpec("two", (PaneSpec("a", ("pwsh.exe",)), PaneSpec("b", ("pwsh.exe",))), "two-column"),),
        target_window="scripts-work",
    )
    backend = WindowsTerminalBackend(executable="wt.exe", runner=PartialLaunch())

    result = backend.launch_managed(plan, launch_id="launch-8", store=store, startup_timeout=0)

    assert result.submission.status.value == "submitted"
    assert result.startup_timed_out
    assert result.spawn_acknowledged_pane_ids == ("launch-8:0:0",)
    assert [pane.state for pane in result.panes] == [ManagedProcessState.RUNNING, ManagedProcessState.RESERVED]


def test_managed_submission_failure_records_failure_without_child_ack(tmp_path, monkeypatch):
    store = ManagedProcessStore(tmp_path / "rejected.sqlite3")

    class RejectedLaunch:
        def __call__(self, command, **kwargs):
            return subprocess.CompletedProcess(command, 31, stdout="", stderr="")

    monkeypatch.setattr("terminal_launcher.backends.windows_terminal.sys.platform", "win32")
    plan = TerminalLaunchPlan(
        (TabSpec("one", (PaneSpec("pwsh", ("pwsh.exe",)),)),), target_window="scripts-work"
    )
    result = WindowsTerminalBackend(executable="wt.exe", runner=RejectedLaunch()).launch_managed(
        plan, launch_id="launch-9", store=store
    )

    assert result.submission.status.value == "failed"
    assert result.panes[0].state is ManagedProcessState.FAILED
    assert not result.panes[0].spawn_acknowledged


def test_managed_relay_persists_spawn_and_exit_receipts_for_real_harmless_child(tmp_path):
    from terminal_launcher.backends._pane_runner import run_managed_payload

    store = ManagedProcessStore(tmp_path / "relay.sqlite3", process_identity_lookup=lambda pid: (pid, 222))
    store.register_submission(
        launch_id="launch-10",
        pane_id="launch-10:0:0",
        window_id="window",
        tab_index=0,
        pane_index=0,
        requested_layout="single",
    )
    result = run_managed_payload(
        ["python", "-c", "pass"],
        None,
        {"store_path": str(store.path), "launch_id": "launch-10", "pane_id": "launch-10:0:0"},
        identity_lookup=lambda pid: (pid, 222),
    )

    [record] = store.enumerate_processes()
    assert result == 0
    assert record.spawn_acknowledged
    assert record.state is ManagedProcessState.EXITED
    assert record.exit_code == 0


def test_managed_relay_records_child_spawn_failure_without_pid(tmp_path):
    from terminal_launcher.backends._pane_runner import run_managed_payload

    store = ManagedProcessStore(tmp_path / "spawn-failure.sqlite3")
    store.register_submission(
        launch_id="launch-11",
        pane_id="launch-11:0:0",
        window_id="window",
        tab_index=0,
        pane_index=0,
        requested_layout="single",
    )

    def missing_child(*_args, **_kwargs):
        raise FileNotFoundError("private argument details are not recorded")

    result = run_managed_payload(
        ["missing.exe"],
        None,
        {"store_path": str(store.path), "launch_id": "launch-11", "pane_id": "launch-11:0:0"},
        popen=missing_child,
    )

    [record] = store.enumerate_processes()
    assert result == 1
    assert record.state is ManagedProcessState.FAILED
    assert record.failure_code == "child_spawn_failed"
    assert record.pid is None
