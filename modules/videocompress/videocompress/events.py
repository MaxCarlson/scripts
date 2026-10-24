"""
Structured progress event models and sinks for videocompress.
Follows INTEGRATION_CONTRACTS.md §5 for CLI/TUI progress reporting.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """A single structured progress event emitted during processing."""

    run_id: str
    sequence: int
    event_type: str  # discovery_started, discovery_item, probe_started, etc.
    phase: str
    schema_version: int = 1
    timestamp: str | None = None
    current: float | None = None
    total: float | None = None
    unit: str = "items"
    source_id: str | None = None
    relative_path: str | None = None
    status: str = "running"
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


ProgressSink = Callable[[ProgressEvent], None]


class ProgressEmitter:
    """Monotonically sequenced event emitter for an operation run."""

    def __init__(self, run_id: str, sink: ProgressSink | None = None) -> None:
        self.run_id = run_id
        self.sink = sink
        self._sequence = 0

    def emit(
        self,
        event_type: str,
        phase: str,
        *,
        current: float | None = None,
        total: float | None = None,
        unit: str = "items",
        source_id: str | None = None,
        relative_path: str | None = None,
        status: str = "running",
        message: str | None = None,
    ) -> ProgressEvent:
        self._sequence += 1
        now = datetime.now(timezone.utc).isoformat()
        event = ProgressEvent(
            run_id=self.run_id,
            sequence=self._sequence,
            event_type=event_type,
            phase=phase,
            timestamp=now,
            current=current,
            total=total,
            unit=unit,
            source_id=source_id,
            relative_path=relative_path,
            status=status,
            message=message,
        )
        if self.sink:
            self.sink(event)
        return event
