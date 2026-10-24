from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from runmux.constants import TERMINAL_STATUSES
from runmux.runner import kill_run
from runmux.store import RunStore
from runmux.tui_adapter import RunmuxTuiAdapter


def test_concurrent_tui_launches_create_distinct_isolated_runs(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runmux-state")
    adapter = RunmuxTuiAdapter(store, store.state_dir / "commands.json")
    argv = [sys.executable, "-c", "print('managed launch')"]
    launch_count = 4
    records = []
    try:
        with ThreadPoolExecutor(max_workers=launch_count) as executor:
            records = list(executor.map(lambda _: adapter.launch(argv, cwd=tmp_path), range(launch_count)))

        assert len({record.id for record in records}) == launch_count
        assert {record.argv_json for record in records} == {json.dumps(argv)}
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            latest = [store.get_run(record.id) for record in records]
            if all(record.status in TERMINAL_STATUSES for record in latest):
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"concurrently launched processes did not finish: {[item.status for item in latest]}")

        assert len(store.list_runs(include_all=True)) == launch_count
        assert all(record.status == "finished" and record.exit_code == 0 for record in latest)
    finally:
        for record in records:
            current = store.get_run(record.id)
            if current.status not in TERMINAL_STATUSES:
                kill_run(store, run_id=current.id, force=True)
