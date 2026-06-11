from __future__ import annotations

import sys
import time
from pathlib import Path

from runmux.runner import create_managed_run
from runmux.store import RunStore


def wait_for_status(
    store: RunStore, run_id: str, status: str, timeout_seconds: float = 10.0
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        record = store.get_run(run_id)
        if record.status == status:
            return
        time.sleep(0.1)
    raise AssertionError(f"Run {run_id} did not reach status {status!r}")


def test_managed_run_captures_output(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    started = create_managed_run(
        store,
        program_args=[sys.executable, "-c", "print('runmux-ok')"],
        cwd=tmp_path,
        name=None,
        force_color=True,
    )

    wait_for_status(store, started.record.id, "finished")
    record = store.get_run(started.record.id)

    assert record.exit_code == 0
    assert b"runmux-ok" in record.log_file.read_bytes()
