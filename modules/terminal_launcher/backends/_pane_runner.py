"""Shell-free relay used to preserve child argv across WT's command grammar."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from importlib import import_module
from pathlib import Path

_MODULE_ROOT = str(Path(__file__).resolve().parents[2])
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

_managed = import_module("terminal_launcher.managed")
ManagedProcessStore = _managed.ManagedProcessStore
process_identity = _managed.process_identity
signal_owned_process_group = _managed.signal_owned_process_group


def run_managed_payload(
    argv: Sequence[str],
    cwd: str | None,
    managed: dict[str, str],
    *,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
    identity_lookup: Callable[[int], tuple[int, int] | None] = process_identity,
    signal_group: Callable[[int], bool] = signal_owned_process_group,
    poll_interval: float = 0.1,
) -> int:
    """Run one owned child and relay durable spawn, exit, and shutdown receipts."""
    store = ManagedProcessStore(managed["store_path"], process_identity_lookup=identity_lookup)
    pane_id = managed["pane_id"]
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
        store.record_failure(pane_id, failure_code="child_spawn_failed")
        return 1

    identity = identity_lookup(child.pid)
    relay_identity = identity_lookup(os.getpid())
    store.record_started(
        pane_id,
        pid=child.pid,
        process_created=identity[1] if identity is not None and identity[0] == child.pid else None,
        relay_pid=os.getpid(),
        relay_process_created=(
            relay_identity[1] if relay_identity is not None and relay_identity[0] == os.getpid() else None
        ),
    )
    while True:
        try:
            exit_code = child.wait(timeout=poll_interval)
            store.record_exit(pane_id, exit_code=exit_code)
            return exit_code
        except subprocess.TimeoutExpired:
            for request in store.pending_shutdown_requests():
                if request.pane_id == pane_id:
                    store.deliver_shutdown_request(pane_id, signal_process_group=signal_group)


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
            isinstance(managed.get(key), str) and managed[key] for key in ("store_path", "launch_id", "pane_id")
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
    except (ValueError, TypeError, json.JSONDecodeError):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
