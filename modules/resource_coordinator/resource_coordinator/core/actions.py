"""
Action pipeline executing operations with verified outcomes and duration tracking.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, Sequence

import anyio

from .processes import ProcessState, ProcessSupervisor

logger = logging.getLogger(__name__)


class ActionOutcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class ActionResult:
    """The reported outcome of an action execution."""

    outcome: ActionOutcome
    message: str = ""
    duration_seconds: float = 0.0
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.outcome == ActionOutcome.SUCCESS

    @property
    def is_ok(self) -> bool:
        return self.outcome in {ActionOutcome.SUCCESS, ActionOutcome.SKIPPED}


class Action(ABC):
    """Abstract action executed as part of a policy."""

    @abstractmethod
    async def execute(self, context: Optional[Dict[str, Any]] = None) -> ActionResult:
        """Execute the action."""
        ...


class StopProcessAction(Action):
    """Action to stop a managed process and verify termination."""

    def __init__(
        self,
        supervisor: ProcessSupervisor,
        wait_until_stopped: bool = True,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.supervisor = supervisor
        self.wait_until_stopped = wait_until_stopped
        self.timeout_seconds = timeout_seconds

    async def execute(self, context: Optional[Dict[str, Any]] = None) -> ActionResult:
        start_time = time.time()
        st = await self.supervisor.status()
        # Initial status is for reporting only. Even STOPPED must pass through
        # the supervisor mutex: an earlier serialized start may still be awaiting.
        success = await self.supervisor.stop(timeout=self.timeout_seconds, origin="coordinator")
        if not success:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                message=f"Failed to stop process '{self.supervisor.name}' within {self.timeout_seconds}s",
                duration_seconds=time.time() - start_time,
            )

        if self.wait_until_stopped:
            is_dead = await self.supervisor.wait_stopped(timeout=self.timeout_seconds)
            if not is_dead:
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    message=f"Process '{self.supervisor.name}' did not terminate completely",
                    duration_seconds=time.time() - start_time,
                )

        return ActionResult(
            outcome=ActionOutcome.SKIPPED if st.state == ProcessState.STOPPED else ActionOutcome.SUCCESS,
            message=f"Process '{self.supervisor.name}' verified stopped",
            duration_seconds=time.time() - start_time,
        )


class StartProcessAction(Action):
    """Action to start a managed process, respecting ownership and manual overrides."""

    def __init__(
        self,
        supervisor: ProcessSupervisor,
        only_if_stopped_by_coordinator: bool = True,
    ) -> None:
        self.supervisor = supervisor
        self.only_if_stopped_by_coordinator = only_if_stopped_by_coordinator

    async def execute(self, context: Optional[Dict[str, Any]] = None) -> ActionResult:
        start_time = time.time()
        if self.supervisor.is_manual_override:
            return ActionResult(
                outcome=ActionOutcome.SKIPPED,
                message=f"Process '{self.supervisor.name}' start skipped: manual override active",
                duration_seconds=time.time() - start_time,
            )

        if self.only_if_stopped_by_coordinator and not self.supervisor.was_stopped_by_coordinator:
            return ActionResult(
                outcome=ActionOutcome.SKIPPED,
                message=f"Process '{self.supervisor.name}' start skipped: was not stopped by coordinator",
                duration_seconds=time.time() - start_time,
            )

        st = await self.supervisor.status()
        if st.state == ProcessState.RUNNING:
            return ActionResult(
                outcome=ActionOutcome.SKIPPED,
                message=f"Process '{self.supervisor.name}' is already running",
                duration_seconds=time.time() - start_time,
            )

        success = await self.supervisor.start(
            origin="coordinator",
            only_if_stopped_by_coordinator=self.only_if_stopped_by_coordinator,
        )
        if success:
            return ActionResult(
                outcome=ActionOutcome.SUCCESS,
                message=f"Process '{self.supervisor.name}' started successfully",
                duration_seconds=time.time() - start_time,
            )
        else:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                message=f"Failed to start process '{self.supervisor.name}'",
                duration_seconds=time.time() - start_time,
            )


class CallableAction(Action):
    """Action wrapping an arbitrary synchronous or asynchronous callable."""

    def __init__(self, func: Callable[[Optional[Dict[str, Any]]], Any], name: str = "custom_action") -> None:
        self.func = func
        self.name = name

    async def execute(self, context: Optional[Dict[str, Any]] = None) -> ActionResult:
        start_time = time.time()
        try:
            res = self.func(context)
            if inspect.isawaitable(res):
                res = await res
            return ActionResult(
                outcome=ActionOutcome.SUCCESS,
                message=f"Action '{self.name}' completed",
                duration_seconds=time.time() - start_time,
                data={"result": res},
            )
        except Exception as exc:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                message=f"Action '{self.name}' failed: {exc}",
                duration_seconds=time.time() - start_time,
            )


class CommandAction(Action):
    """Action executing a safe external command without shell interpolation."""

    def __init__(
        self,
        command: Sequence[str],
        timeout_seconds: float = 15.0,
        name: str = "command_action",
    ) -> None:
        self.command = list(command)
        self.timeout_seconds = timeout_seconds
        self.name = name

    async def execute(self, context: Optional[Dict[str, Any]] = None) -> ActionResult:
        start_time = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_seconds)
            duration = time.time() - start_time
            if proc.returncode == 0:
                return ActionResult(
                    outcome=ActionOutcome.SUCCESS,
                    message=f"Command '{self.name}' exited 0",
                    duration_seconds=duration,
                    data={"stdout": stdout.decode("utf-8", errors="replace")},
                )
            else:
                return ActionResult(
                    outcome=ActionOutcome.FAILURE,
                    message=f"Command '{self.name}' exited {proc.returncode}: {stderr.decode('utf-8', errors='replace')}",
                    duration_seconds=duration,
                )
        except asyncio.TimeoutError:
            with anyio.CancelScope(shield=True):
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                message=f"Command '{self.name}' timed out after {self.timeout_seconds}s",
                duration_seconds=time.time() - start_time,
            )
        except asyncio.CancelledError:
            with anyio.CancelScope(shield=True):
                if "proc" in locals() and proc.returncode is None:
                    proc.kill()
                    await proc.wait()
            raise
        except Exception as exc:
            return ActionResult(
                outcome=ActionOutcome.FAILURE,
                message=f"Command '{self.name}' failed to run: {exc}",
                duration_seconds=time.time() - start_time,
            )
