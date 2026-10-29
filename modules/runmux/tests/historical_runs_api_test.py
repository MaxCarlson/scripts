from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from runmux.store import RunNotFoundError, RunStore
from runmux.telemetry_store import TelemetryStore
from runmux.web import create_runmux_web_app
from runmux.web_adapter import ReadOnlyRunmux


def _insert_run(
    store: RunStore,
    run_id: str,
    *,
    created_at: str,
    status: str = "finished",
    name: str | None = "sample",
    started_at: str | None = None,
    ended_at: str | None = None,
    exit_code: int | None = 0,
    restart_of: str | None = None,
    duplicate_of: str | None = None,
) -> None:
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            """INSERT INTO runs (
                id, numeric_id, name, status, created_at, updated_at, started_at, ended_at,
                exit_code, pid, supervisor_pid, program, argv_json, cwd, env_overrides_json,
                port, auth_token, log_path, command_line, restart_of, duplicate_of, rows, columns
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, 24, 80)""",
            (
                run_id,
                int(run_id[-6:], 16),
                name,
                status,
                created_at,
                created_at,
                started_at,
                ended_at,
                exit_code,
                sys.executable,
                "[]",
                str(store.state_dir),
                "{}",
                "test-token",
                str(store.state_dir / "secret-output.log"),
                "secret command arguments",
                restart_of,
                duplicate_of,
            ),
        )


def _record(store: RunStore, index: int) -> str:
    run_id = f"20261024-120000-{index:06x}"
    _insert_run(store, run_id, created_at="2026-10-24T12:00:00+00:00")
    return run_id


def test_query_runs_keyset_is_stable_and_rejects_changed_filters(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    created = "2026-10-24T12:00:00+00:00"
    ids = [f"20261024-120000-{index:06x}" for index in range(5)]
    for run_id in ids:
        _insert_run(store, run_id, created_at=created)

    first = store.query_runs(limit=2)
    assert [item.id for item in first.items] == sorted(ids, reverse=True)[:2]
    assert first.has_more is True

    _insert_run(store, "20261024-130000-000099", created_at="2026-10-24T13:00:00+00:00")
    second = store.query_runs(limit=2, cursor=first.next_cursor)
    assert [item.id for item in second.items] == sorted(ids, reverse=True)[2:4]
    assert second.has_more is True

    with pytest.raises(ValueError, match="filters do not match"):
        store.query_runs(limit=2, cursor=first.next_cursor, status="failed")


def test_query_runs_filters_are_applied_in_sql_and_run_ids_remain_identity(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    created = "2026-10-24T12:00:00+00:00"
    _insert_run(
        store, "20261024-120000-000001", created_at=created, ended_at=created, name="Same", status="failed", exit_code=2
    )
    _insert_run(
        store,
        "20261024-120000-000002",
        created_at=created,
        ended_at=created,
        name="Same",
        status="finished",
        exit_code=0,
    )
    _insert_run(
        store,
        "20261024-120000-000003",
        created_at=created,
        ended_at=created,
        name="Other",
        status="lost",
        exit_code=None,
    )

    page = store.query_runs(name="same", failed_only=True)
    assert [record.id for record in page.items] == ["20261024-120000-000001"]
    assert [record.id for record in store.query_runs(lost_only=True).items] == ["20261024-120000-000003"]
    assert store.query_runs(state="terminal", limit=1).page_size == 1
    bounded = store.query_runs(
        since="2026-10-24T12:00:00Z",
        until=1792843200,
        time_field="ended_at",
        name="same",
        sort_by="numeric_id",
        sort_dir="asc",
        include_total=True,
    )
    assert [record.id for record in bounded.items] == ["20261024-120000-000001", "20261024-120000-000002"]
    assert bounded.total_count == 2


def test_lineage_uses_explicit_restart_and_duplicate_ids(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    created = "2026-10-24T12:00:00+00:00"
    root = "20261024-120000-000001"
    restarted = "20261024-120001-000002"
    duplicate = "20261024-120002-000003"
    _insert_run(store, root, created_at=created)
    _insert_run(store, restarted, created_at=created, restart_of=root)
    _insert_run(store, duplicate, created_at=created, duplicate_of=root)

    lineage = store.get_run_lineage(root)
    assert lineage.root_run_id == root
    assert lineage.ancestors == []
    assert {node.id for node in lineage.descendants} == {restarted, duplicate}
    assert lineage.total_restarts == 1
    assert lineage.total_duplicates == 1
    restarted_lineage = store.get_run_lineage(restarted)
    assert [(node.id, node.relationship) for node in restarted_lineage.ancestors] == [(root, "parent_restart")]


def test_history_adapter_and_routes_are_allowlisted_and_truthful(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    run_id = "20261024-120000-000001"
    child_id = "20261024-120001-000002"
    created = "2026-10-24T12:00:00+00:00"
    _insert_run(store, run_id, created_at=created, status="finished", started_at=created, ended_at=created)
    _insert_run(store, child_id, created_at=created, status="running", restart_of=run_id)
    telemetry_store = TelemetryStore(tmp_path)
    telemetry_store.record_event(
        run_id,
        "pause",
        timestamp=1792843200.0,
        reason="secret reason",
        details={"token": "secret"},
    )
    telemetry_store.record_event(run_id, "resume", timestamp=1792843201.0)
    telemetry_store.record_event(run_id, "checkpoint", timestamp=1792843202.0)

    backend = ReadOnlyRunmux(tmp_path)
    payload = backend.query_runs_history(limit=1)
    assert payload["page_size"] == 1
    item = payload["items"][0]
    assert item["id"] in {run_id, child_id}
    assert not {"argv_json", "cwd", "env_overrides_json", "auth_token", "port", "log_path", "command_line"} & set(item)

    events = backend.get_run_events(run_id)
    event_rows = events["events"]
    assert {event["provenance"] for event in event_rows} == {"registry_record", "telemetry_store"}
    assert any(event["event_type"] == "pause" for event in event_rows)
    assert any(event["event_type"] == "restarted_by" and event["related_run_id"] == child_id for event in event_rows)
    assert all("secret" not in json.dumps(event).lower() for event in event_rows)
    first_event_page = backend.get_run_events(run_id, limit=2)
    assert first_event_page["has_more"] is True
    event_cursor = first_event_page["next_cursor"]
    all_event_pages = list(first_event_page["events"])
    while event_cursor:
        next_event_page = backend.get_run_events(run_id, limit=2, cursor=event_cursor)
        all_event_pages.extend(next_event_page["events"])
        event_cursor = next_event_page["next_cursor"]
    assert {event["event_type"] for event in all_event_pages} >= {"pause", "resume", "checkpoint"}
    assert len({(event["timestamp"], event["event_type"], event.get("event_id")) for event in all_event_pages}) == len(
        all_event_pages
    )
    with pytest.raises(ValueError, match="limit must be between"):
        backend.get_run_events(run_id, limit=0)
    lineage = backend.get_run_lineage(run_id)
    assert lineage["run_id"] == run_id
    assert lineage["descendants"][0]["id"] == child_id

    app = create_runmux_web_app(tmp_path, login_code="secret", enable_telemetry_history=False)
    paths = {route.path for route in app.routes}
    assert {"/api/runs", "/api/runs/history", "/api/runs/{run_id}/events", "/api/runs/{run_id}/lineage"} <= paths


def test_history_adapter_rejects_invalid_cursor_and_unknown_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    _record(store, 1)
    backend = ReadOnlyRunmux(tmp_path)
    with pytest.raises(ValueError, match="cursor is invalid"):
        backend.query_runs_history(cursor="not-a-cursor")
    with pytest.raises(RunNotFoundError):
        backend.get_run_events("20261024-120000-999999")


def test_ten_thousand_run_registry_queries_remain_page_bounded(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    base = "2026-10-24T12:00:00+00:00"
    with sqlite3.connect(store.db_path) as connection:
        connection.executemany(
            """INSERT INTO runs (
                id, numeric_id, name, status, created_at, updated_at, started_at, ended_at, exit_code,
                program, argv_json, cwd, env_overrides_json, auth_token, log_path, command_line,
                restart_of, duplicate_of, rows, columns
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, '[]', '/', '{}', 'token', '/secret/path', 'cmd',
                NULL, NULL, 24, 80)""",
            (
                (
                    f"20261024-120000-{index:06x}",
                    index,
                    f"worker-{index % 100}",
                    "failed" if index % 10 == 0 else "finished",
                    f"2026-10-24T12:{index // 600:02d}:{(index // 10) % 60:02d}+00:00",
                    base,
                    base,
                    1 if index % 10 == 0 else 0,
                    sys.executable,
                )
                for index in range(10_000)
            ),
        )

    start = time.perf_counter()
    first = store.query_runs(limit=50)
    first_ms = (time.perf_counter() - start) * 1000
    start = time.perf_counter()
    middle = store.query_runs(limit=50, cursor=first.next_cursor)
    next_ms = (time.perf_counter() - start) * 1000
    start = time.perf_counter()
    filtered = store.query_runs(limit=50, status="failed", name="worker-2")
    filtered_ms = (time.perf_counter() - start) * 1000

    assert len(first.items) == len(middle.items) == len(filtered.items) == 50
    assert all(record.status == "failed" and "worker-2" in (record.name or "") for record in filtered.items)
    print(f"10k registry query benchmark: first={first_ms:.2f}ms next={next_ms:.2f}ms filtered={filtered_ms:.2f}ms")

    app = create_runmux_web_app(tmp_path, login_code="history-test-login", enable_telemetry_history=False)
    query = {
        "limit": 50,
        "sort_by": "created_at",
        "sort_dir": "desc",
        "state": "terminal",
        "name": "worker-0",
        "name_exact": "true",
        "exit_code": 1,
        "failed_only": "true",
    }
    with TestClient(app, base_url="http://localhost") as client:
        client.headers.update({"Origin": "http://localhost"})
        unauthorized = client.get("/api/runs/history", params=query)
        assert unauthorized.status_code == 401
        login = client.post(
            "/auth/login",
            json={"code": "history-test-login"},
            headers={"Origin": "http://localhost"},
        )
        assert login.status_code == 204

        first_http = client.get("/api/runs/history", params=query)
        assert first_http.status_code == 200
        first_payload = first_http.json()
        first_items = first_payload["items"]
        assert first_payload["page_size"] == len(first_items) == 50
        assert first_payload["has_more"] is True
        assert first_payload["total_count"] is None
        assert all(item["status"] == "failed" and item["name"] == "worker-0" for item in first_items)
        assert len({item["id"] for item in first_items}) == 50
        assert not {"argv_json", "cwd", "env_overrides_json", "auth_token", "log_path", "command_line"} & set(
            first_items[0]
        )

        cursor = first_payload["next_cursor"]
        mismatched = client.get("/api/runs/history", params={**query, "cursor": cursor, "status": "failed"})
        assert mismatched.status_code == 400

        # A newer insert is beyond the first page's captured upper boundary.
        inserted_id = "20261025-000000-ffffff"
        _insert_run(
            store,
            inserted_id,
            created_at="2026-10-25T00:00:00+00:00",
            status="failed",
            name="worker-0",
            exit_code=1,
        )
        second_http = client.get("/api/runs/history", params={**query, "cursor": cursor})
        assert second_http.status_code == 200
        second_payload = second_http.json()
        second_ids = {item["id"] for item in second_payload["items"]}
        assert len(second_ids) == 50
        assert inserted_id not in second_ids
        assert not ({item["id"] for item in first_items} & second_ids)

        # Membership changes are not snapshot-isolated: a later matching row can disappear.
        fresh_first = client.get("/api/runs/history", params=query)
        assert fresh_first.status_code == 200
        mutation_cursor = fresh_first.json()["next_cursor"]
        before_mutation = client.get("/api/runs/history", params={**query, "cursor": mutation_cursor})
        assert before_mutation.status_code == 200
        before_items = before_mutation.json()["items"]
        assert len(before_items) == 50
        removed_from_filter = before_items[0]["id"]
        with sqlite3.connect(store.db_path) as connection:
            connection.execute("UPDATE runs SET status = 'lost' WHERE id = ?", (removed_from_filter,))
        after_mutation = client.get("/api/runs/history", params={**query, "cursor": mutation_cursor})
        assert after_mutation.status_code == 200
        after_payload = after_mutation.json()
        after_ids = {item["id"] for item in after_payload["items"]}
        before_ids = {item["id"] for item in before_items}
        assert removed_from_filter not in after_ids
        assert len(after_ids) == 50
        assert len(before_ids - after_ids) == 1
        assert len(after_ids - before_ids) == 1, (
            "A later record shifts into the page after a matching run leaves the filter"
        )
        assert after_payload["has_more"] is False

        maximum = client.get("/api/runs/history", params={"limit": 200})
        assert maximum.status_code == 200
        assert maximum.json()["page_size"] <= 200
        too_large = client.get("/api/runs/history", params={"limit": 201})
        assert too_large.status_code == 400
