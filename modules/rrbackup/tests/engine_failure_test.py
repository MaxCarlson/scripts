from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from rrbackup.engine import BackupEngine
from rrbackup.locking import ProcessIdentity
from rrbackup.models import ExecutionMode, RunState
from rrbackup.policy import CpuPolicy
from rrbackup.profile import BackupProfile
from rrbackup.restic import ExecutionResult
from rrbackup.state import RunStateStore

UTC = timezone.utc
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def make_profile(tmp_path) -> BackupProfile:
    password = tmp_path / "password.txt"
    sources = tmp_path / "sources.txt"
    password.write_text("secret", encoding="utf-8")
    sources.write_text("C:\\\n", encoding="utf-8")

    return BackupProfile(
        name="local",
        repository=str(tmp_path / "repo"),
        password_file=str(password),
        sources_file=str(sources),
        excludes_file=None,
        status_file=str(tmp_path / "state" / "status.json"),
        log_file=str(tmp_path / "logs" / "backup.log"),
        lock_file=str(tmp_path / "state" / "backup.lock"),
        tag="local-main",
        restic_executable="restic",
        restore_root=str(tmp_path / "restore"),
        cpu_policy=CpuPolicy(max_wait=timedelta(0)),
    )


class FakeLock:
    def __init__(self):
        self.identity = ProcessIdentity(pid=123, create_time=456.0)
        self.released = False

    def acquire(self):
        return None

    def release(self):
        self.released = True


def test_lock_factory_failure_records_terminal_failure(tmp_path):
    profile = make_profile(tmp_path)
    store = RunStateStore(tmp_path / "state-store")

    def fail_lock_factory():
        raise RuntimeError("factory failed")

    engine = BackupEngine(
        profile,
        state_store=store,
        lock_factory=fail_lock_factory,
    )

    with pytest.raises(RuntimeError, match="factory failed"):
        engine.run(respect_cpu_policy=False)

    latest = store.load_latest()
    assert latest.state == RunState.FAILURE
    assert "construct backup lock" in latest.reason


def test_malformed_summary_records_failure_and_releases_lock(tmp_path):
    profile = make_profile(tmp_path)
    store = RunStateStore(tmp_path / "state-store")
    lock = FakeLock()

    def executor(command, **kwargs):
        return ExecutionResult(
            command=command,
            mode=kwargs["mode"],
            executed=True,
            return_code=0,
            started_utc=NOW,
            finished_utc=NOW + timedelta(seconds=1),
            output=(
                '{"message_type":"summary","files_new":"not-an-integer"}\n',
            ),
        )

    engine = BackupEngine(
        profile,
        state_store=store,
        lock_factory=lambda: lock,
        command_executor=executor,
    )

    with pytest.raises(ValueError):
        engine.run(mode=ExecutionMode.RUN, respect_cpu_policy=False)

    latest = store.load_latest()
    assert latest.state == RunState.FAILURE
    assert "finalize backup result" in latest.reason
    assert lock.released
