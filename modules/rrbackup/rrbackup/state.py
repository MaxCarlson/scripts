"""Atomic persistence for backup run records."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .models import RunRecord, RunState, utc_now


def atomic_write_json(path: os.PathLike[str] | str, payload: Dict[str, Any]) -> None:
    """Atomically replace a JSON file using a temporary file in the same directory."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".{0}.".format(target.name),
        suffix=".tmp",
        dir=str(target.parent),
        text=True,
    )
    temporary_path = Path(temporary_name)

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=4, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(target))
    except Exception:
        try:
            temporary_path.unlink(missing_ok=True)
        finally:
            raise


def read_json(path: os.PathLike[str] | str) -> Dict[str, Any]:
    """Read a JSON object, returning an empty mapping when the file is absent."""

    target = Path(path)
    if not target.exists():
        return {}

    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object in {0}.".format(target))
    return payload


class RunStateStore:
    """Persist current, historical, and last-success run records."""

    def __init__(self, state_root: os.PathLike[str] | str) -> None:
        self.state_root = Path(state_root)
        self.runs_root = self.state_root / "runs"
        self.latest_path = self.state_root / "latest.json"
        self.last_success_path = self.state_root / "last-success.json"

    def save(self, record: RunRecord) -> None:
        """Persist a run and update current pointers atomically."""

        self.runs_root.mkdir(parents=True, exist_ok=True)
        payload = record.to_dict()
        atomic_write_json(self.runs_root / "{0}.json".format(record.run_id), payload)
        atomic_write_json(self.latest_path, payload)

        if record.state == RunState.SUCCESS:
            atomic_write_json(self.last_success_path, payload)

    def load_run(self, run_id: str) -> Optional[RunRecord]:
        """Load one run by identifier."""

        path = self.runs_root / "{0}.json".format(run_id)
        if not path.exists():
            return None
        return RunRecord.from_dict(read_json(path))

    def load_latest(self) -> Optional[RunRecord]:
        """Load the latest attempted run."""

        if not self.latest_path.exists():
            return None
        return RunRecord.from_dict(read_json(self.latest_path))

    def load_last_success(self) -> Optional[RunRecord]:
        """Load the last real successful run.

        Dry runs, previews, skips, failures, and interruptions never update this pointer.
        """

        if not self.last_success_path.exists():
            return None
        return RunRecord.from_dict(read_json(self.last_success_path))

    def reconcile_stale_running(
        self,
        process_checker: Callable[[int, float], bool],
        *,
        reason: str = "Previous process ended without recording a terminal state.",
    ) -> Optional[RunRecord]:
        """Mark a stale running record as interrupted.

        The caller supplies a PID-and-create-time checker so reconciliation can use
        the same process-identity semantics as the lock implementation.
        """

        latest = self.load_latest()
        if latest is None or latest.state != RunState.RUNNING:
            return latest

        if latest.pid is None or latest.process_start_time is None:
            reconciled = latest.transition(
                RunState.INTERRUPTED,
                now=utc_now(),
                reason=reason + " Process identity was not recorded.",
            )
            self.save(reconciled)
            return reconciled

        if process_checker(latest.pid, latest.process_start_time):
            return latest

        reconciled = latest.transition(
            RunState.INTERRUPTED,
            now=utc_now(),
            reason=reason,
        )
        self.save(reconciled)
        return reconciled
