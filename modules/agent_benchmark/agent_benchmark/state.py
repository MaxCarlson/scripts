"""Small durable benchmark receipt and OS-held exclusive command lock.

The receipt survives process exit; the OS lock does not. Execution commands
reconcile a pending receipt before dispatch and never override unresolved work.
"""

from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
import uuid

from .lifecycle import DispatchGuard


def read_pending(state: Path) -> dict | None:
    path = state / "pending.json"
    if not path.exists():
        return None
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(receipt, dict) or receipt.get("version") != 1
                or not isinstance(receipt.get("token"), str)
                or not isinstance(receipt.get("evidence_dir"), str)):
            raise ValueError("Invalid receipt")
        return receipt
    except (OSError, ValueError) as error:
        raise RuntimeError("Unreadable pending receipt; preserve state and resolve unresolved worker before dispatch") from error


@contextmanager
def command_lock(state: Path):
    """Serializes run/cleanup across invocations; crash releases the OS lock."""
    state.mkdir(parents=True, exist_ok=True)
    with (state / "command.lock").open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError("Another benchmark command is active; dispatch/cleanup refused") from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def reserve(state: Path, evidence_dir: Path) -> dict:
    if read_pending(state) is not None:
        raise RuntimeError("Unresolved worker receipt blocks dispatch; inspect status and cleanup first")
    receipt = {"version": 1, "token": uuid.uuid4().hex, "evidence_dir": str(evidence_dir.resolve())}
    with (state / "pending.json").open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle)
        handle.flush()
        os.fsync(handle.fileno())
    return receipt


def release(state: Path, receipt: dict) -> None:
    current = read_pending(state)
    if current is None or current["token"] != receipt["token"]:
        raise RuntimeError("Pending receipt ownership changed; refusing release")
    (state / "pending.json").unlink()


def journal_at(evidence_dir: Path) -> dict:
    try:
        value = json.loads((evidence_dir / "lifecycle.json").read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Invalid lifecycle journal")
        return value
    except (OSError, ValueError) as error:
        raise RuntimeError("Lifecycle journal unavailable; preserve pending receipt and workspace") from error


def safely_finished(evidence_dir: Path) -> bool:
    try:
        journal = journal_at(evidence_dir)
        if journal.get("stage") in ("not_submitted", "preflight_failed"):
            return True
        return journal.get("termination", {}).get("confirmed") is True
    except (RuntimeError, AttributeError):
        return False


@contextmanager
def reserved_trial(state: Path, evidence_dir: Path, *, lock_held: bool = False):
    """One shared reservation lifecycle for scored and diagnostic execution."""
    with (nullcontext() if lock_held else command_lock(state)):
        receipt = reserve(state, evidence_dir)
        guard = DispatchGuard()
        try:
            yield guard
        finally:
            # Receipt contents never establish that a possible submission ended.
            if not guard.submission_started or safely_finished(evidence_dir):
                release(state, receipt)
