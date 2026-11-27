"""Shell-free relay with one-time pane claims and bounded adaptive interruption polling."""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from importlib import import_module
from pathlib import Path

_MODULE_ROOT = str(Path(__file__).resolve().parents[2])
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

_managed = import_module("terminal_launcher.managed")
InterruptionState = _managed.InterruptionState
ManagedProcessStore = _managed.ManagedProcessStore
ProcessIdentity = _managed.ProcessIdentity
ProcessLiveness = _managed.ProcessLiveness
ProcessLivenessLookup = _managed.ProcessLivenessLookup
process_identity = _managed.process_identity
process_liveness = _managed.process_liveness
signal_owned_process_group = _managed.signal_owned_process_group


def _safe_diagnostic(message: str) -> None:
    print(f"terminal-launcher relay: {message}", file=sys.stderr, flush=True)


def run_managed_payload(
    argv: Sequence[str],
    cwd: str | None,
    managed: dict[str, str],
    *,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
    identity_lookup: ProcessIdentity = process_identity,
    liveness_lookup: ProcessLivenessLookup = process_liveness,
    signal_group: Callable[[int], bool] = signal_owned_process_group,
    store_factory: Callable[..., ManagedProcessStore] = ManagedProcessStore,
    poll_interval: float = 0.05,
    max_poll_interval: float = 1.0,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    """Claim a pane before spawning; persist receipts and supervise one child only."""
    if poll_interval <= 0 or max_poll_interval < poll_interval:
        raise ValueError("poll intervals must be positive and max_poll_interval >= poll_interval")
    store = store_factory(
        managed["store_path"],
        process_identity_lookup=identity_lookup,
        process_liveness_lookup=liveness_lookup,
    )
    launch_id = managed["launch_id"]
    pane_id = managed["pane_id"]
    relay_pid = os.getpid()
    relay_identity = identity_lookup(relay_pid)
    if relay_identity is None or relay_identity[0] != relay_pid:
        _safe_diagnostic(f"cannot prove relay identity; pane {pane_id} was not started")
        return 2

    claim_token = store.claim_pane(
        launch_id,
        pane_id,
        relay_pid=relay_pid,
        relay_process_created=relay_identity[1],
    )
    if claim_token is None:
        return 0

    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    try:
        child = popen(
            list(argv),
            cwd=cwd,
            shell=False,
            creationflags=creationflags,
            close_fds=True,
        )
    except OSError:
        try:
            store.record_spawn_failure(
                launch_id,
                pane_id,
                claim_token=claim_token,
                failure_code="child_spawn_failed",
            )
        except (OSError, sqlite3.Error, ValueError):
            _safe_diagnostic(f"spawn failed and receipt persistence failed for claimed pane {pane_id}")
        return 1

    child_identity = identity_lookup(child.pid)
    process_created = (
        child_identity[1] if child_identity is not None and child_identity[0] == child.pid else None
    )

    def persist_start() -> bool:
        try:
            store.record_started(
                launch_id,
                pane_id,
                claim_token=claim_token,
                pid=child.pid,
                process_created=process_created,
                relay_pid=relay_pid,
                relay_process_created=relay_identity[1],
            )
            return True
        except (OSError, sqlite3.Error, ValueError):
            return False

    started_persisted = False
    for attempt in range(3):
        if persist_start():
            started_persisted = True
            break
        if attempt < 2:
            sleeper(0.02 * (attempt + 1))

    if not started_persisted:
        _safe_diagnostic(
            f"start receipt persistence failed for pane {pane_id}, child PID {child.pid}; "
            "relay retains supervision and will retry persistence"
        )

    interval = poll_interval
    while True:
        try:
            exit_code = child.wait(timeout=interval)
            break
        except subprocess.TimeoutExpired:
            if not started_persisted and persist_start():
                started_persisted = True
            try:
                state = store.get_interruption_state(pane_id)
                if state is InterruptionState.PENDING:
                    store.deliver_interruption(
                        pane_id,
                        relay_pid=relay_pid,
                        relay_process_created=relay_identity[1],
                        signal_process_group=signal_group,
                    )
                    interval = poll_interval
                else:
                    interval = min(max_poll_interval, max(poll_interval, interval * 2))
            except (OSError, sqlite3.Error, ValueError) as exc:
                _safe_diagnostic(
                    f"pane-specific control query failed for pane {pane_id} ({type(exc).__name__}); "
                    "relay retains child supervision"
                )
                interval = min(max_poll_interval, max(poll_interval, interval * 2))

    if not started_persisted:
        started_persisted = persist_start()
    if started_persisted:
        for attempt in range(3):
            try:
                store.record_exit(launch_id, pane_id, claim_token=claim_token, exit_code=exit_code)
                break
            except (OSError, sqlite3.Error, ValueError):
                if attempt == 2:
                    _safe_diagnostic(f"exit receipt persistence failed for pane {pane_id}, child PID {child.pid}")
                else:
                    sleeper(0.02 * (attempt + 1))
    else:
        _safe_diagnostic(f"child PID {child.pid} exited without durable start or exit receipts for pane {pane_id}")
    return exit_code


def _decode_payload(encoded: str) -> object:
    padding = "=" * (-len(encoded) % 4)
    return json.loads(base64.urlsafe_b64decode(encoded + padding))


def run_payload(encoded: str, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> int:
    """Decode a launch payload and run its argv without shell interpretation."""
    payload = _decode_payload(encoded)
    if isinstance(payload, dict):
        argv = payload.get("argv")
        cwd = payload.get("cwd")
        managed = payload.get("managed")
    else:
        argv, cwd = payload
        managed = None
    if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) for arg in argv):
        raise ValueError("payload must contain a non-empty string argument vector")
    if cwd is not None and not isinstance(cwd, str):
        raise ValueError("payload cwd must be a string or null")
    if managed is not None:
        if not isinstance(managed, dict) or not all(
            isinstance(managed.get(key), str) and managed[key]
            for key in ("store_path", "launch_id", "pane_id")
        ):
            raise ValueError("managed payload must contain store_path, launch_id, and pane_id")
        return run_managed_payload(argv, cwd, managed)
    return runner(argv, cwd=cwd, shell=False, check=False).returncode


def main(args: Sequence[str] | None = None) -> int:
    values = list(sys.argv[1:] if args is None else args)
    if len(values) != 1:
        return 2
    try:
        return run_payload(values[0])
    except (ValueError, TypeError, json.JSONDecodeError, sqlite3.Error, OSError) as exc:
        _safe_diagnostic(f"relay could not persist or decode its request ({type(exc).__name__})")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
