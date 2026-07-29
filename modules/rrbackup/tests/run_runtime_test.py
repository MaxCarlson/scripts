from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from rrbackup import run_runtime
from rrbackup.models import RunRecord, RunState
from rrbackup.run_monitor import MonitorOutcome
from rrbackup.state import RunStateStore
from rrbackup.viewer import build_demo_records


UTC = timezone.utc
NOW = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)


def _args():
    return SimpleNamespace(
        backup_name="local-main",
        json=False,
        plain=False,
        markdown=False,
        print_command_only=False,
        dry_run=False,
        ignore_cpu_policy=False,
        tag=[],
        exclude=[],
        restic_arg=[],
    )


def test_interactive_named_run_routes_through_confirmation_monitor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = build_demo_records(now=NOW)[0]
    inventory = SimpleNamespace(records=(record,))
    observed = {}

    monkeypatch.setattr(
        run_runtime,
        "_selected_records",
        lambda args: (inventory, [record]),
    )
    monkeypatch.setattr(run_runtime, "interactive_available", lambda: True)

    def monitor(records, callback):
        observed["records"] = records
        observed["callback"] = callback
        return MonitorOutcome(cancelled=True, payloads=tuple(), exit_codes=tuple())

    monkeypatch.setattr(run_runtime, "run_backup_monitor", monitor)
    monkeypatch.setattr(
        run_runtime.cli_runtime,
        "_run_one",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("interactive execution must wait for monitor confirmation")
        ),
    )

    assert run_runtime.handle_run(_args()) == run_runtime.cli_runtime.EXIT_OK
    assert observed["records"] == [record]
    assert callable(observed["callback"])


def test_progress_persistence_updates_running_record_metadata(tmp_path) -> None:
    store = RunStateStore(tmp_path / "state")
    record = RunRecord.create(
        profile="local-main",
        backup_set="local-main",
        now=NOW,
    ).transition(RunState.RUNNING, now=NOW)
    store.save(record)
    observed = []
    persistence = run_runtime._ProgressPersistence(
        store,
        "local-main",
        observed.append,
        interval_seconds=0,
    )

    persistence.handle_line(
        '{"message_type":"status","seconds_elapsed":10,"percent_done":0.5,'
        '"total_files":20,"files_done":10,"total_bytes":200,"bytes_done":100}'
    )

    latest = store.load_latest()
    assert latest is not None
    assert latest.metadata["progress"]["percent_display"] == pytest.approx(50.0)
    assert len(observed) == 1
