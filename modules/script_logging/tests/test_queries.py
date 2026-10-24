from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from script_logging import (
    Page,
    ProgramStatistics,
    open_invocation_reader,
    list_invocations,
    get_program_statistics,
    get_command_statistics,
)
from script_logging.invocation_store import InvocationStore


def test_query_pagination_and_deterministic_order(tmp_path: Path):
    db_path = tmp_path / "invocations.sqlite3"
    store = InvocationStore(db_path)

    base_time = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(15):
        t = base_time + timedelta(seconds=i)
        inv_id = store.start_invocation(
            program_id="module:mangadl",
            invoked_name="mangadl",
            argv=("mangadl", "run", f"--step={i}"),
            cwd=Path("/work"),
            origin="launcher",
            started_at_utc=t.isoformat(),
        )
        store.finish_invocation(
            inv_id,
            exit_code=0 if i % 2 == 0 else 1,
            status="exited",
            finished_at_utc=(t + timedelta(milliseconds=100)).isoformat(),
        )

    reader = open_invocation_reader(db_path)
    page1 = reader.list_invocations(limit=5)
    assert len(page1.items) == 5
    assert page1.has_more is True
    assert page1.next_cursor is not None

    page2 = reader.list_invocations(limit=5, cursor=page1.next_cursor)
    assert len(page2.items) == 5
    assert page2.has_more is True
    assert page2.next_cursor is not None

    # Ensure no overlap between page 1 and page 2
    ids1 = {r.invocation_id for r in page1.items}
    ids2 = {r.invocation_id for r in page2.items}
    assert ids1.isdisjoint(ids2)

    page3 = reader.list_invocations(limit=5, cursor=page2.next_cursor)
    assert len(page3.items) == 5
    assert page3.has_more is False
    assert page3.next_cursor is None

    # Verify deterministic ordering: newer invocations appear first
    all_items = page1.items + page2.items + page3.items
    assert len(all_items) == 15
    for j in range(len(all_items) - 1):
        prev = all_items[j]
        curr = all_items[j + 1]
        assert (prev.started_epoch_ms, prev.invocation_id) > (curr.started_epoch_ms, curr.invocation_id)

    # Program statistics
    stats = reader.get_program_statistics("module:mangadl")
    assert isinstance(stats, ProgramStatistics)
    assert stats.total_starts == 15
    assert stats.success_count == 8
    assert stats.failure_count == 7


def test_query_filters(tmp_path: Path):
    db_path = tmp_path / "invocations.sqlite3"
    store = InvocationStore(db_path)

    t1 = datetime(2026, 10, 24, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 24, 11, 0, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)

    id1 = store.start_invocation(
        program_id="module:mangadl",
        invoked_name="mangadl",
        argv=("mangadl", "dl"),
        cwd=Path("/tmp"),
        started_at_utc=t1.isoformat(),
    )
    store.finish_invocation(id1, exit_code=0, status="exited")

    id2 = store.start_invocation(
        program_id="module:compresser",
        invoked_name="compresser",
        argv=("compresser", "zip"),
        cwd=Path("/tmp"),
        started_at_utc=t2.isoformat(),
    )
    store.finish_invocation(id2, exit_code=2, status="exited")

    id3 = store.start_invocation(
        program_id="module:mangadl",
        invoked_name="mdl",
        argv=("mdl", "status"),
        cwd=Path("/tmp"),
        started_at_utc=t3.isoformat(),
    )
    store.finish_invocation(id3, status="launch_failed")

    reader = open_invocation_reader(db_path)

    # Filter by program_id
    prog_page = reader.list_invocations(program_id="module:compresser")
    assert len(prog_page.items) == 1
    assert prog_page.items[0].invocation_id == id2

    # Filter by invoked_name
    name_page = reader.list_invocations(invoked_name="mdl")
    assert len(name_page.items) == 1
    assert name_page.items[0].invocation_id == id3

    # Filter by status
    failed_page = reader.list_invocations(status="launch_failed")
    assert len(failed_page.items) == 1
    assert failed_page.items[0].invocation_id == id3

    # Filter by time range
    time_page = reader.list_invocations(since=t2, before=t3 + timedelta(seconds=1))
    assert {r.invocation_id for r in time_page.items} == {id2, id3}


def test_invalid_cursor_handling(tmp_path: Path):
    db_path = tmp_path / "invocations.sqlite3"
    InvocationStore(db_path)
    reader = open_invocation_reader(db_path)

    with pytest.raises(ValueError, match="Invalid pagination cursor"):
        reader.list_invocations(cursor="not-valid-base64!")

    with pytest.raises(ValueError, match="Invalid pagination cursor"):
        # Valid base64 but does not decode to epoch:id
        import base64
        invalid_payload = base64.urlsafe_b64encode(b"malformed").decode("ascii")
        reader.list_invocations(cursor=invalid_payload)


def test_list_unique_commands_and_command_statistics(tmp_path: Path):
    db_path = tmp_path / "invocations.sqlite3"
    store = InvocationStore(db_path)

    id1 = store.start_invocation("module:mangadl", "mangadl", ("mangadl", "run"), "/tmp")
    store.finish_invocation(id1, exit_code=0, status="exited")
    id2 = store.start_invocation("module:mangadl", "mangadl", ("mangadl", "run"), "/tmp")
    store.finish_invocation(id2, exit_code=0, status="exited")
    id3 = store.start_invocation("module:mangadl", "mangadl", ("mangadl", "stop"), "/tmp")
    store.finish_invocation(id3, exit_code=1, status="exited")

    reader = open_invocation_reader(db_path)
    patterns = reader.list_unique_commands(program_id="module:mangadl")
    assert isinstance(patterns, Page)
    assert len(patterns.items) == 2

    # Check command statistics
    run_pattern = next(p for p in patterns.items if "run" in p.pattern_argv)
    stats = reader.get_command_statistics(run_pattern.pattern_id)
    assert stats is not None
    assert stats.invocation_count == 2
    assert stats.success_count == 2
    assert stats.failure_count == 0

    missing_stats = reader.get_command_statistics("nonexistent_pattern_id")
    assert missing_stats is None


def test_public_convenience_functions(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "invocations.sqlite3"
    monkeypatch.setenv("SCRIPT_LOGGING_INVOCATION_DB", str(db_path))

    store = InvocationStore(db_path)
    inv_id = store.start_invocation("module:test", "test", ("test", "--help"), "/tmp")
    store.finish_invocation(inv_id, exit_code=0, status="exited")

    page = list_invocations(limit=10)
    assert len(page.items) == 1
    assert page.items[0].invocation_id == inv_id

    stats = get_program_statistics("module:test")
    assert stats.total_starts == 1
    assert stats.success_count == 1

    pattern_id = page.items[0].pattern_id
    cmd_stats = get_command_statistics(pattern_id)
    assert cmd_stats is not None
    assert cmd_stats.invocation_count == 1
