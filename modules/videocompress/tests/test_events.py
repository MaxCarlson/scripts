"""
Tests for structured progress events in videocompress.
"""

from __future__ import annotations

import json
from videocompress.events import ProgressEmitter, ProgressEvent


def test_progress_event_serialization():
    event = ProgressEvent(
        run_id="run-1",
        sequence=1,
        event_type="probe_item",
        phase="probe",
        current=3,
        total=10,
        source_id="src-1",
        relative_path="clip.mp4",
        status="running",
        message="Probing clip.mp4",
    )
    d = event.to_dict()
    assert d["sequence"] == 1
    assert d["event_type"] == "probe_item"
    assert d["current"] == 3
    assert d["total"] == 10
    json_str = event.to_json()
    parsed = json.loads(json_str)
    assert parsed["run_id"] == "run-1"


def test_progress_emitter_increments_sequence():
    events: list[ProgressEvent] = []
    emitter = ProgressEmitter(run_id="run-abc", sink=events.append)

    emitter.emit("discovery_started", phase="discovery", total=5)
    emitter.emit("discovery_item", phase="discovery", current=1, total=5, message="Found 1")
    emitter.emit("discovery_completed", phase="discovery", current=5, total=5)

    assert len(events) == 3
    assert events[0].sequence == 1
    assert events[1].sequence == 2
    assert events[2].sequence == 3
    assert events[0].event_type == "discovery_started"
    assert events[2].event_type == "discovery_completed"
