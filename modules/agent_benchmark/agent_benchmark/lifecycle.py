"""Bounded termination reconciliation and narrowly owned fixture workspaces.

No job status, including ``cancelled``, is proof of termination. A concrete
bridge adapter must obtain fresh remote session/turn/tool evidence. This module
has no process-management capability and does not own benchmark result scoring.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
import math
from pathlib import Path
import shutil
import tempfile
import time
from typing import Protocol, TypeVar
import warnings


@dataclass(frozen=True)
class WorkerHandle:
    job_id: str
    session_id: str
    message_id: str
    workspace: Path


@dataclass(frozen=True)
class Observation:
    """Fresh evidence for exactly the handle's session and submitted turn.

    ``correlated`` requires matching session/message IDs, not just an idle server.
    ``turn_finished`` requires completed/aborted matching assistant evidence.
    ``tools_running`` must conservatively include incomplete tool calls. Unknown
    tool state must be represented as True. Raw cached job state is diagnostic.
    These fields must never be populated from a worker's completion report.
    """

    job_status: str
    session_state: str | None
    turn_finished: bool
    tools_running: bool
    correlated: bool
    diagnostic: str = ""

    @property
    def confirms_termination(self) -> bool:
        return self.correlated and self.session_state == "idle" and self.turn_finished and not self.tools_running


class LifecycleBridge(Protocol):
    """Use supported bridge cancellation; observe must bypass terminal job caches.

    Implementations must use cancellable, bounded I/O and must not start any new
    work while observing. Use one fresh session per benchmark trial. Never map a
    missing/error response to idle or to finished. No synchronous blocking I/O.
    """

    async def cancel(self, handle: WorkerHandle) -> object: ...

    async def observe(self, handle: WorkerHandle) -> Observation: ...


@dataclass(frozen=True)
class TerminationDecision:
    handle: WorkerHandle
    confirmed: bool
    cancellation_requested: bool
    grace_seconds: float
    elapsed_seconds: float
    last_observation: Observation | None
    diagnostics: tuple[str, ...]


_T = TypeVar("_T")


def _consume_finished(task: asyncio.Task) -> None:
    # Do not leave an unobserved exception if a transport completes after timeout.
    if not task.cancelled():
        task.exception()


async def _bounded(awaitable: Awaitable[_T], deadline: float) -> _T:
    task = asyncio.ensure_future(awaitable)
    try:
        done, _ = await asyncio.wait({task}, timeout=max(0, deadline - time.monotonic()))
        if not done:
            raise TimeoutError("confirmation deadline reached")
        return task.result()
    finally:
        if not task.done():
            # Do not await an uncooperative transport after the absolute deadline.
            # Its remote outcome remains uncertain, so callers preserve resources.
            task.cancel()
            task.add_done_callback(_consume_finished)


def _positive_finite(value: float, name: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and greater than zero")


async def confirm_termination(
    bridge: LifecycleBridge,
    handle: WorkerHandle,
    *,
    grace_seconds: float = 10.0,
    poll_seconds: float = 0.1,
    cancel_first: bool = True,
) -> TerminationDecision:
    """Reconcile within one budget, including the cancellation request itself.

    An observation timeout must call this reconciliation before cleanup/retry.
    Use cancel_first=False after ordinary task completion, still requiring fresh
    independent evidence. External cancellation propagates; it never authorizes
    workspace deletion. The caller must persist decisions/handles as evidence.
    """
    _positive_finite(grace_seconds, "grace_seconds")
    _positive_finite(poll_seconds, "poll_seconds")
    start = time.monotonic()
    deadline = start + grace_seconds
    diagnostics: list[str] = []
    observation = None
    confirmed = False
    if cancel_first:
        try:
            await _bounded(bridge.cancel(handle), deadline)
            diagnostics.append("Cancellation acknowledged; termination still requires fresh evidence")
        except Exception as error:  # Adapter I/O boundary; CancelledError still propagates.
            diagnostics.append(f"Cancellation request uncertain: {type(error).__name__}")
    while time.monotonic() < deadline:
        try:
            observation = await _bounded(bridge.observe(handle), deadline)
            if observation.confirms_termination:
                confirmed = True
                break
            diagnostics.append(
                f"Unconfirmed: job={observation.job_status}, session={observation.session_state}, "
                f"finished={observation.turn_finished}, tools_running={observation.tools_running}, "
                f"correlated={observation.correlated}"
            )
            if observation.diagnostic:
                diagnostics.append(observation.diagnostic)
        except Exception as error:  # Adapter I/O boundary; CancelledError still propagates.
            diagnostics.append(f"Fresh observation failed: {type(error).__name__}")
        remaining = deadline - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(min(poll_seconds, remaining))
    if not confirmed:
        diagnostics.append("Termination unresolved at deadline; preserve workspace and stop dispatch")
    # Avoid repeating polling state hundreds of times in compact trial metadata.
    diagnostics = list(dict.fromkeys(diagnostics))
    return TerminationDecision(
        handle, confirmed, cancel_first, grace_seconds, time.monotonic() - start, observation, tuple(diagnostics)
    )


@dataclass(frozen=True)
class OwnedWorkspace:
    root: Path
    path: Path
    allocation_id: str


class DispatchGuard:
    """A sticky safety stop, not a scheduler. One instance belongs to one batch."""

    def __init__(self) -> None:
        self.unresolved: TerminationDecision | None = None

    def record(self, decision: TerminationDecision) -> None:
        if not decision.confirmed:
            if self.unresolved is None:
                self.unresolved = decision
            warnings.warn(
                f"Unresolved worker {decision.handle.job_id}; preserve {decision.handle.workspace}; "
                "further benchmark dispatch halted",
                RuntimeWarning,
                stacklevel=2,
            )

    def allocate(self, root: Path) -> OwnedWorkspace:
        """Allocate a fresh empty directory, refusing after any unresolved worker."""
        if self.unresolved is not None:
            raise RuntimeError(f"Dispatch halted: unresolved job {self.unresolved.handle.job_id}")
        root = root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        path = Path(tempfile.mkdtemp(prefix="trial-", dir=root))
        return OwnedWorkspace(root, path, path.name)


@dataclass(frozen=True)
class CleanupOutcome:
    removed: bool
    attempts: int
    diagnostic: str = ""


def cleanup_workspace(
    workspace: OwnedWorkspace,
    decision: TerminationDecision,
    *,
    attempts: int = 3,
    retry_seconds: float = 0.05,
) -> CleanupOutcome:
    """Remove only a confirmed, exactly owned workspace; never update task scores.

    Shared OpenCode/LM Studio processes are outside this module's ownership.
    Filesystem failure is returned separately from independent evaluation. This
    is a trusted-fixture safeguard, not protection against hostile filesystem races.
    """
    if attempts < 1 or not math.isfinite(retry_seconds) or retry_seconds < 0:
        raise ValueError("Cleanup requires positive attempts and finite nonnegative retry_seconds")
    path = workspace.path
    if not decision.confirmed or decision.handle.workspace != path:
        return CleanupOutcome(False, 0, "Termination unconfirmed or workspace does not match job")
    if (
        path != workspace.root / workspace.allocation_id
        or not workspace.allocation_id.startswith("trial-")
        or path == workspace.root
        or path.is_symlink()
        or path.is_junction()
        or workspace.root.resolve() != workspace.root
        or path.resolve().parent != workspace.root
    ):
        return CleanupOutcome(False, 0, "Workspace ownership or resolved path check failed")
    for attempt in range(1, attempts + 1):
        try:
            shutil.rmtree(path)
            return CleanupOutcome(True, attempt)
        except FileNotFoundError:
            if not path.exists():
                return CleanupOutcome(True, attempt)
            return CleanupOutcome(False, attempt, "Cleanup encountered a missing entry; workspace preserved")
        except OSError as error:
            lock_like = isinstance(error, PermissionError) or getattr(error, "winerror", None) in (32, 33)
            if not lock_like or attempt == attempts:
                return CleanupOutcome(False, attempt, f"Cleanup failed: {type(error).__name__}")
            time.sleep(retry_seconds)
    raise AssertionError("unreachable")
