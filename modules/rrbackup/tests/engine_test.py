from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from rrbackup.engine import BackupEngine
from rrbackup.locking import AlreadyRunningError, ProcessIdentity
from rrbackup.models import ExecutionMode, RunState
from rrbackup.policy import CpuDecision, CpuPolicy, WaitResult
from rrbackup.profile import BackupProfile
from rrbackup.restic import ExecutionResult, ResticExecutionError, ResticInterrupted
from rrbackup.state import RunStateStore

UTC = timezone.utc
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def make_profile(tmp_path) -> BackupProfile:
    password = tmp_path / "password.txt"
    sources = tmp_path / "sources.txt"
    excludes = tmp_path / "excludes.txt"
    password.write_text("secret", encoding="utf-8")
    sources.write_text("C:\\\n", encoding="utf-8")
    excludes.write_text("C:\\Temp\\**\n", encoding="utf-8")

    return BackupProfile(
        name="local",
        repository=str(tmp_path / "repo"),
        password_file=str(password),
        sources_file=str(sources),
        excludes_file=str(excludes),
        status_file=str(tmp_path / "state" / "legacy-status.json"),
        log_file=str(tmp_path / "logs" / "backup.log"),
        lock_file=str(tmp_path / "state" / "backup.lock"),
        tag="local-main",
        restic_executable="restic",
        restore_root=str(tmp_path / "restore"),
        cpu_policy=CpuPolicy(max_wait=timedelta(0)),
    )


class FakeLock:
    def __init__(self, events=None, acquire_error=None):
        self.events = events if events is not None else []
        self.acquire_error = acquire_error
        self.identity = ProcessIdentity(pid=123, create_time=456.0, executable="python")
        self.acquired = False

    def acquire(self):
        self.events.append("lock-acquire")
        if self.acquire_error is not None:
            raise self.acquire_error
        self.acquired = True

    def release(self):
        self.events.append("lock-release")
        self.acquired = False


def execution_result(command, mode, *, return_code=0, output=()):
    return ExecutionResult(
        command=command,
        mode=mode,
        executed=mode != ExecutionMode.PREVIEW,
        return_code=None if mode == ExecutionMode.PREVIEW else return_code,
        started_utc=NOW,
        finished_utc=NOW + timedelta(seconds=1),
        output=tuple(output),
    )


def successful_summary(snapshot_id="snapshot-1"):
    return json.dumps(
        {
            "message_type": "summary",
            "snapshot_id": snapshot_id,
            "files_new": 2,
            "files_changed": 1,
            "data_added_packed": 100,
            "total_duration": 1.5,
        }
    ) + "\n"


def accepted_wait_result() -> WaitResult:
    decision = CpuDecision(
        should_run=True,
        cpu_percent=10.0,
        threshold=25.0,
        overdue=False,
        age=timedelta(hours=1),
        reason="CPU accepted.",
    )
    return WaitResult(
        decision=decision,
        attempts=1,
        waited=timedelta(0),
        deadline_reached=False,
    )


def rejected_wait_result() -> WaitResult:
    decision = CpuDecision(
        should_run=False,
        cpu_percent=100.0,
        threshold=85.0,
        overdue=True,
        age=None,
        reason="CPU rejected.",
    )
    return WaitResult(
        decision=decision,
        attempts=2,
        waited=timedelta(minutes=5),
        deadline_reached=True,
    )


def test_build_backup_command_preserves_production_semantics(tmp_path):
    profile = make_profile(tmp_path)
    command = BackupEngine(profile).build_backup_command()

    assert command.argv == (
        "restic",
        "-r",
        profile.repository,
        "backup",
        "--json",
        "--use-fs-snapshot",
        "--files-from-verbatim",
        profile.sources_file,
        "--iexclude-file",
        profile.excludes_file,
        "--exclude-caches",
        "--tag",
        "local-main",
    )
    assert command.environment["RESTIC_PASSWORD_FILE"] == profile.password_file


def test_preview_has_no_state_lock_or_log_side_effects(tmp_path):
    profile = make_profile(tmp_path)
    store = RunStateStore(tmp_path / "state-store")
    calls = []

    def executor(command, **kwargs):
        calls.append(kwargs)
        return execution_result(command, ExecutionMode.PREVIEW)

    engine = BackupEngine(
        profile,
        state_store=store,
        lock_factory=lambda: pytest.fail("preview must not create a lock"),
        command_executor=executor,
    )

    result = engine.run(mode=ExecutionMode.PREVIEW)

    assert not result.execution.executed
    assert store.load_latest() is None
    assert calls == [{"mode": ExecutionMode.PREVIEW, "echo": False}]
    assert not (tmp_path / "logs" / "backup.log").exists()


def test_cpu_skip_occurs_before_lock_or_execution(tmp_path):
    profile = make_profile(tmp_path)
    store = RunStateStore(tmp_path / "state-store")

    engine = BackupEngine(
        profile,
        state_store=store,
        lock_factory=lambda: pytest.fail("skipped backup must not acquire a lock"),
        command_executor=lambda *args, **kwargs: pytest.fail(
            "skipped backup must not execute Restic"
        ),
        cpu_waiter=lambda *args, **kwargs: rejected_wait_result(),
    )

    result = engine.run()

    assert result.record.state == RunState.SKIPPED
    assert result.execution is None
    assert result.record.metadata["deadline_reached"] is True
    assert store.load_last_success() is None


def test_cpu_wait_precedes_lock_and_execution(tmp_path):
    profile = make_profile(tmp_path)
    store = RunStateStore(tmp_path / "state-store")
    events = []
    lock = FakeLock(events)

    def waiter(*args, **kwargs):
        events.append("cpu")
        return accepted_wait_result()

    def executor(command, **kwargs):
        events.append("execute")
        return execution_result(
            command,
            kwargs["mode"],
            output=[successful_summary()],
        )

    engine = BackupEngine(
        profile,
        state_store=store,
        lock_factory=lambda: lock,
        command_executor=executor,
        cpu_waiter=waiter,
    )

    result = engine.run()

    assert result.record.state == RunState.SUCCESS
    assert events == ["cpu", "lock-acquire", "execute", "lock-release"]


def test_real_success_records_snapshot_and_last_success(tmp_path):
    profile = make_profile(tmp_path)
    store = RunStateStore(tmp_path / "state-store")
    lock = FakeLock()

    engine = BackupEngine(
        profile,
        state_store=store,
        lock_factory=lambda: lock,
        command_executor=lambda command, **kwargs: execution_result(
            command,
            kwargs["mode"],
            output=[successful_summary("abcdef12")],
        ),
    )

    result = engine.run(respect_cpu_policy=False)

    assert result.record.state == RunState.SUCCESS
    assert result.record.snapshot_id == "abcdef12"
    assert result.summary.snapshot_id == "abcdef12"
    assert store.load_last_success() == result.record
    assert result.record.pid == 123
    assert result.record.process_start_time == 456.0


def test_dry_run_never_updates_last_success(tmp_path):
    profile = make_profile(tmp_path)
    store = RunStateStore(tmp_path / "state-store")

    engine = BackupEngine(
        profile,
        state_store=store,
        lock_factory=lambda: FakeLock(),
        command_executor=lambda command, **kwargs: execution_result(
            command,
            kwargs["mode"],
            output=[successful_summary("must-not-count")],
        ),
    )

    result = engine.run(
        mode=ExecutionMode.DRY_RUN,
        respect_cpu_policy=False,
    )

    assert result.record.state == RunState.DRY_RUN
    assert result.record.snapshot_id is None
    assert store.load_last_success() is None
    assert "no snapshot" in result.record.reason.lower()


def test_nonzero_restic_exit_records_failure(tmp_path):
    profile = make_profile(tmp_path)
    store = RunStateStore(tmp_path / "state-store")

    engine = BackupEngine(
        profile,
        state_store=store,
        lock_factory=lambda: FakeLock(),
        command_executor=lambda command, **kwargs: execution_result(
            command,
            kwargs["mode"],
            return_code=3,
        ),
    )

    result = engine.run(respect_cpu_policy=False)

    assert result.record.state == RunState.FAILURE
    assert result.record.exit_code == 3
    assert store.load_last_success() is None


def test_active_lock_is_recorded_as_skipped(tmp_path):
    profile = make_profile(tmp_path)
    store = RunStateStore(tmp_path / "state-store")
    lock = FakeLock(acquire_error=AlreadyRunningError("already running"))

    engine = BackupEngine(
        profile,
        state_store=store,
        lock_factory=lambda: lock,
        command_executor=lambda *args, **kwargs: pytest.fail("must not execute"),
    )

    result = engine.run(respect_cpu_policy=False)

    assert result.record.state == RunState.SKIPPED
    assert "already running" in result.record.reason
    assert "lock-release" not in lock.events


def test_executor_exception_records_failure_and_releases_lock(tmp_path):
    profile = make_profile(tmp_path)
    store = RunStateStore(tmp_path / "state-store")
    lock = FakeLock()

    def fail_execute(command, **kwargs):
        raise ResticExecutionError("cannot start")

    engine = BackupEngine(
        profile,
        state_store=store,
        lock_factory=lambda: lock,
        command_executor=fail_execute,
    )

    with pytest.raises(ResticExecutionError):
        engine.run(respect_cpu_policy=False)

    assert store.load_latest().state == RunState.FAILURE
    assert "cannot start" in store.load_latest().reason
    assert not lock.acquired


def test_restic_interruption_records_interrupted_result(tmp_path):
    profile = make_profile(tmp_path)
    store = RunStateStore(tmp_path / "state-store")
    lock = FakeLock()

    def interrupt(command, **kwargs):
        result = execution_result(command, kwargs["mode"], return_code=130)
        raise ResticInterrupted(result)

    engine = BackupEngine(
        profile,
        state_store=store,
        lock_factory=lambda: lock,
        command_executor=interrupt,
    )

    result = engine.run(respect_cpu_policy=False)

    assert result.record.state == RunState.INTERRUPTED
    assert result.record.exit_code == 130
    assert result.execution.interrupted is False
    assert not lock.acquired


def test_cpu_wait_exception_records_failure(tmp_path):
    profile = make_profile(tmp_path)
    store = RunStateStore(tmp_path / "state-store")

    def fail_wait(*args, **kwargs):
        raise RuntimeError("sampler failed")

    engine = BackupEngine(
        profile,
        state_store=store,
        cpu_waiter=fail_wait,
    )

    with pytest.raises(RuntimeError, match="sampler failed"):
        engine.run()

    assert store.load_latest().state == RunState.FAILURE
    assert "CPU-window" in store.load_latest().reason
