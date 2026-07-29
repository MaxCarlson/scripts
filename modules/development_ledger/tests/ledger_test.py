from __future__ import annotations

import json
from pathlib import Path

import pytest

from development_ledger.ledger import LedgerError, append_event, read_events


def test_append_event_writes_compact_jsonl_and_rejects_duplicates(tmp_path: Path):
    event = {"event_id": "one", "event_type": "validation_run", "value": "β"}

    append_event(tmp_path, event)

    assert read_events(tmp_path) == [event]
    line = (tmp_path / "RUNS.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads(line) == event
    with pytest.raises(LedgerError, match="already exists"):
        append_event(tmp_path, event)


def test_read_events_rejects_invalid_json(tmp_path: Path):
    (tmp_path / "RUNS.jsonl").write_text("not-json\n", encoding="utf-8")

    with pytest.raises(LedgerError, match="Invalid JSON"):
        read_events(tmp_path)
