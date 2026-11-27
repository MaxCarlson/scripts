"""Typed backend contract and structured preview/launch results."""

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .models import TerminalLaunchPlan

if TYPE_CHECKING:
    from .managed import ManagedProcessRecord


class LaunchStatus(str, Enum):
    SUBMITTED = "submitted"
    FAILED = "failed"
    NOOP = "no_op"


class ProcessState(str, Enum):
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PlannedOperation:
    """A safe summary of a backend operation; process arguments are omitted."""

    action: str
    tab_index: int
    pane_index: int
    tab_title: str
    pane_title: str
    layout: str
    cwd: str | None


@dataclass(frozen=True, slots=True)
class LaunchPreview:
    """Side-effect-free summary of the terminal operations a plan requires."""

    backend: str
    operations: tuple[PlannedOperation, ...]
    warnings: tuple[str, ...] = ()
    capabilities: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class LaunchResult:
    """Terminal request status, with child process state always explicit."""

    status: LaunchStatus
    backend: str
    process_state: ProcessState = ProcessState.UNKNOWN
    returncode: int | None = None
    diagnostic: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ManagedLaunchResult:
    """Request outcome plus durable pane receipts observed before timeout."""

    launch_id: str
    submission: LaunchResult
    panes: tuple["ManagedProcessRecord", ...] = ()
    startup_timed_out: bool = False

    @property
    def spawn_acknowledged_pane_ids(self) -> tuple[str, ...]:
        return tuple(pane.pane_id for pane in self.panes if pane.spawn_acknowledged)


@runtime_checkable
class TerminalBackend(Protocol):
    """Minimal contract shared by terminal launcher backends."""

    def preview(self, plan: TerminalLaunchPlan) -> LaunchPreview:
        """Describe planned operations without starting processes."""

    def launch(self, plan: TerminalLaunchPlan) -> LaunchResult:
        """Submit the operation plan and report submission separately from pane state."""
