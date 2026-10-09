"""Behavioral tests for reusable logging and history persistence."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import logging

from script_logging import EventFormatter, EventRecord, HistoryStore, RunRecord, StoreHandler


def _run(at: datetime, *, name: str = "job", status: str = "success") -> RunRecord:
    timestamp = at.isoformat()
    return RunRecord(
        source="sample", entity_type="job", entity_id=name, display_name=name,
        started_at=timestamp, finished_at=(at + timedelta(seconds=3)).isoformat(),
        status=status, duration_sec=3.0, exit_code=0 if status == "success" else 1,
        stdout="hello", stderr="", metadata={"label": name},
    )


def test_run_history_queries_and_output_retention(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    first_time = datetime(2026, 10, 1, tzinfo=timezone.utc)
    first = _run(first_time)
    second = _run(first_time + timedelta(days=1), status="failure")
    store.append_run(first)
    store.append_run(second)
    store.append_run(first)  # idempotent import

    runs = store.list_runs(source="sample", entity_type="job", entity_id="job")
    assert [run.record_id for run in runs] == [second.record_id, first.record_id]
    assert len(store.list_runs(since=(first_time + timedelta(hours=1)).isoformat())) == 1
    assert store.get_run(first.record_id).metadata == {"label": "job"}

    assert store.prune_output((first_time + timedelta(hours=1)).isoformat(), source="sample") == 1
    assert store.get_run(first.record_id).stdout is None
    assert store.get_run(second.record_id).stdout == "hello"
    assert len(store.list_runs()) == 2


def test_store_handles_concurrent_appends_and_source_scoped_clear(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def write(index: int) -> None:
        record = _run(now + timedelta(seconds=index), name=f"job-{index}")
        store.append_run(record)
        store.append_event(EventRecord(source="sample", event_type="DONE", occurred_at=record.finished_at, message="done"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(24)))

    assert len(store.list_runs(source="sample")) == 24
    assert len(store.list_events(source="sample")) == 24
    store.append_event(EventRecord(source="other", event_type="KEEP", occurred_at=now.isoformat(), message="keep"))
    store.clear(source="sample")
    assert store.list_runs(source="sample") == []
    assert [event.event_type for event in store.list_events()] == ["KEEP"]


def test_modular_formatter_and_standard_logger_bridge(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    logger = logging.getLogger("test.script_logging")
    handler = StoreHandler(store, source="sample")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info("started", extra={"event_type": "JOB_START"})
    finally:
        logger.removeHandler(handler)

    events = store.list_events(source="sample")
    assert len(events) == 1
    assert events[0].event_type == "JOB_START"
    assert events[0].message == "started"

    record = logging.LogRecord("sample", logging.ERROR, __file__, 1, "bad result", (), None)
    formatter = EventFormatter(fields=("date", "time", "type", "message"), colors=True)
    rendered = formatter.format(record)
    assert "ERROR" in rendered and "bad result" in rendered and "\x1b[31m" in rendered
    assert "\x1b[" not in EventFormatter(fields=("message",), colors=False).format(record)
    custom = EventFormatter(fields=("time", "message"), colors=True, color_map={"ERROR": "\x1b[35m"})
    assert custom.format(record).startswith("\x1b[35m")
